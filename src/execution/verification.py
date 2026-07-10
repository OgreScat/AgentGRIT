"""
AgentGRIT 2.0 - Tool Verification Layer

CRITICAL FIX: Prevents the "model said it did it, but nothing happened" failure mode.

Problem from earlier session:
- GLM-4.7-flash ran for 30+ minutes
- Printed "PERFECT! FILE CREATED!" messages
- ZERO files actually created - model was hallucinating

Solution: VERIFY_OR_FAIL gate
- Every tool call MUST return verifiable evidence
- No claim without proof
- Filesystem checks, exit codes, diff inspection are MANDATORY
"""

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class VerificationStatus(Enum):
    """Status of a verification check."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class VerificationResult:
    """Result of a single verification check."""
    check_name: str
    status: VerificationStatus
    expected: Any
    actual: Any
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ToolExecutionResult:
    """
    Complete result of a tool execution with verification.
    
    This is the authoritative record - the agent's claim of success
    is only valid if verifications pass.
    """
    tool_name: str
    command: str | None
    
    # Raw execution results
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    
    # Verification results
    verifications: list[VerificationResult]
    all_passed: bool
    
    # Evidence (proof of work)
    evidence: dict[str, Any] = field(default_factory=dict)
    
    # Final verdict
    success: bool = False
    failure_reason: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:500] if self.stdout else None,
            "stderr": self.stderr[:500] if self.stderr else None,
            "duration_ms": self.duration_ms,
            "verifications": [
                {
                    "check": v.check_name,
                    "status": v.status.value,
                    "message": v.message,
                }
                for v in self.verifications
            ],
            "all_passed": self.all_passed,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "evidence": self.evidence,
        }


class ToolVerifier:
    """
    Verification engine for tool executions.
    
    RULE: No claim without proof.
    """
    
    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()
        self.verification_log: list[ToolExecutionResult] = []
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def verify_file_created(
        self,
        path: str,
        min_size: int = 0,
        expected_content_hash: str | None = None,
    ) -> VerificationResult:
        """
        Verify a file was actually created.
        
        Checks:
        - File exists
        - File is not empty (unless min_size=0)
        - Content hash matches (if provided)
        """
        full_path = Path(path)
        if not full_path.is_absolute():
            full_path = self.workspace / path
        
        # Check exists
        if not full_path.exists():
            return VerificationResult(
                check_name="file_created",
                status=VerificationStatus.FAILED,
                expected=f"File exists: {path}",
                actual="File does not exist",
                message=f"VERIFICATION FAILED: File not created at {path}",
            )
        
        # Check is file (not directory)
        if not full_path.is_file():
            return VerificationResult(
                check_name="file_created",
                status=VerificationStatus.FAILED,
                expected="Regular file",
                actual="Directory or special file",
                message=f"VERIFICATION FAILED: {path} is not a regular file",
            )
        
        # Check size
        size = full_path.stat().st_size
        if size < min_size:
            return VerificationResult(
                check_name="file_created",
                status=VerificationStatus.FAILED,
                expected=f"Size >= {min_size} bytes",
                actual=f"Size = {size} bytes",
                message=f"VERIFICATION FAILED: File too small ({size} < {min_size})",
            )
        
        # Check content hash
        if expected_content_hash:
            actual_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()[:16]
            if actual_hash != expected_content_hash:
                return VerificationResult(
                    check_name="file_created",
                    status=VerificationStatus.FAILED,
                    expected=f"Hash: {expected_content_hash}",
                    actual=f"Hash: {actual_hash}",
                    message="VERIFICATION FAILED: Content hash mismatch",
                )
        
        # All checks passed
        return VerificationResult(
            check_name="file_created",
            status=VerificationStatus.PASSED,
            expected=f"File at {path}",
            actual=f"File exists, {size} bytes",
            message=f"✓ File created: {path} ({size} bytes)",
        )
    
    def verify_file_modified(
        self,
        path: str,
        modified_after: datetime,
    ) -> VerificationResult:
        """Verify a file was modified after a given time."""
        full_path = Path(path)
        if not full_path.is_absolute():
            full_path = self.workspace / path
        
        if not full_path.exists():
            return VerificationResult(
                check_name="file_modified",
                status=VerificationStatus.FAILED,
                expected=f"File exists: {path}",
                actual="File does not exist",
                message=f"VERIFICATION FAILED: File not found at {path}",
            )
        
        mtime = datetime.fromtimestamp(full_path.stat().st_mtime)
        if mtime < modified_after:
            return VerificationResult(
                check_name="file_modified",
                status=VerificationStatus.FAILED,
                expected=f"Modified after {modified_after}",
                actual=f"Modified at {mtime}",
                message=f"VERIFICATION FAILED: File not modified (mtime: {mtime})",
            )
        
        return VerificationResult(
            check_name="file_modified",
            status=VerificationStatus.PASSED,
            expected=f"Modified after {modified_after}",
            actual=f"Modified at {mtime}",
            message=f"✓ File modified: {path}",
        )
    
    def verify_file_contains(
        self,
        path: str,
        expected_strings: list[str],
    ) -> VerificationResult:
        """Verify a file contains expected strings."""
        full_path = Path(path)
        if not full_path.is_absolute():
            full_path = self.workspace / path
        
        if not full_path.exists():
            return VerificationResult(
                check_name="file_contains",
                status=VerificationStatus.FAILED,
                expected=f"File exists with content",
                actual="File does not exist",
                message=f"VERIFICATION FAILED: File not found at {path}",
            )
        
        try:
            content = full_path.read_text()
        except Exception as e:
            return VerificationResult(
                check_name="file_contains",
                status=VerificationStatus.ERROR,
                expected="Readable file",
                actual=str(e),
                message=f"VERIFICATION ERROR: Cannot read {path}: {e}",
            )
        
        missing = [s for s in expected_strings if s not in content]
        if missing:
            return VerificationResult(
                check_name="file_contains",
                status=VerificationStatus.FAILED,
                expected=f"Contains: {expected_strings}",
                actual=f"Missing: {missing}",
                message=f"VERIFICATION FAILED: File missing expected content: {missing}",
            )
        
        return VerificationResult(
            check_name="file_contains",
            status=VerificationStatus.PASSED,
            expected=f"Contains {len(expected_strings)} strings",
            actual="All strings found",
            message=f"✓ File contains expected content",
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # COMMAND EXECUTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def verify_command_success(
        self,
        exit_code: int,
        allowed_codes: list[int] | None = None,
    ) -> VerificationResult:
        """Verify command exited with expected code."""
        allowed = allowed_codes or [0]
        
        if exit_code in allowed:
            return VerificationResult(
                check_name="command_exit_code",
                status=VerificationStatus.PASSED,
                expected=f"Exit code in {allowed}",
                actual=f"Exit code: {exit_code}",
                message=f"✓ Command succeeded (exit {exit_code})",
            )
        
        return VerificationResult(
            check_name="command_exit_code",
            status=VerificationStatus.FAILED,
            expected=f"Exit code in {allowed}",
            actual=f"Exit code: {exit_code}",
            message=f"VERIFICATION FAILED: Command failed (exit {exit_code})",
        )
    
    def verify_no_errors_in_output(
        self,
        stdout: str,
        stderr: str,
        error_patterns: list[str] | None = None,
    ) -> VerificationResult:
        """Verify output doesn't contain error patterns."""
        patterns = error_patterns or [
            "error:", "Error:", "ERROR:",
            "failed", "Failed", "FAILED",
            "exception", "Exception", "EXCEPTION",
            "traceback", "Traceback",
            "fatal:", "Fatal:", "FATAL:",
        ]
        
        combined = stdout + stderr
        found_errors = [p for p in patterns if p.lower() in combined.lower()]
        
        if found_errors:
            return VerificationResult(
                check_name="no_errors",
                status=VerificationStatus.FAILED,
                expected="No error patterns",
                actual=f"Found: {found_errors}",
                message=f"VERIFICATION FAILED: Error patterns in output: {found_errors}",
            )
        
        return VerificationResult(
            check_name="no_errors",
            status=VerificationStatus.PASSED,
            expected="No error patterns",
            actual="Clean output",
            message="✓ No errors in output",
        )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # GIT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def verify_git_changes(
        self,
        expected_files: list[str] | None = None,
        min_changed_files: int = 1,
    ) -> VerificationResult:
        """Verify git has uncommitted changes."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
            )
            
            if result.returncode != 0:
                return VerificationResult(
                    check_name="git_changes",
                    status=VerificationStatus.ERROR,
                    expected="Git repository",
                    actual=result.stderr,
                    message="VERIFICATION ERROR: Not a git repository or git error",
                )
            
            changed_files = [
                line.split()[-1] 
                for line in result.stdout.strip().split("\n") 
                if line.strip()
            ]
            
            if len(changed_files) < min_changed_files:
                return VerificationResult(
                    check_name="git_changes",
                    status=VerificationStatus.FAILED,
                    expected=f"At least {min_changed_files} changed files",
                    actual=f"{len(changed_files)} changed files",
                    message=f"VERIFICATION FAILED: No git changes detected",
                )
            
            if expected_files:
                missing = [f for f in expected_files if f not in changed_files]
                if missing:
                    return VerificationResult(
                        check_name="git_changes",
                        status=VerificationStatus.FAILED,
                        expected=f"Changes to: {expected_files}",
                        actual=f"Missing changes to: {missing}",
                        message=f"VERIFICATION FAILED: Expected files not modified",
                    )
            
            return VerificationResult(
                check_name="git_changes",
                status=VerificationStatus.PASSED,
                expected=f"Git changes present",
                actual=f"Changed: {changed_files}",
                message=f"✓ Git changes detected: {len(changed_files)} files",
            )
            
        except Exception as e:
            return VerificationResult(
                check_name="git_changes",
                status=VerificationStatus.ERROR,
                expected="Git check",
                actual=str(e),
                message=f"VERIFICATION ERROR: {e}",
            )
    
    def verify_git_diff_not_empty(self) -> VerificationResult:
        """Verify git diff produces output."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
            )
            
            if not result.stdout.strip():
                return VerificationResult(
                    check_name="git_diff",
                    status=VerificationStatus.FAILED,
                    expected="Non-empty diff",
                    actual="Empty diff",
                    message="VERIFICATION FAILED: Git diff is empty",
                )
            
            return VerificationResult(
                check_name="git_diff",
                status=VerificationStatus.PASSED,
                expected="Non-empty diff",
                actual=result.stdout[:200],
                message=f"✓ Git diff present",
            )
            
        except Exception as e:
            return VerificationResult(
                check_name="git_diff",
                status=VerificationStatus.ERROR,
                expected="Git diff",
                actual=str(e),
                message=f"VERIFICATION ERROR: {e}",
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CODE QUALITY
    # ═══════════════════════════════════════════════════════════════════════════
    
    def verify_python_syntax(self, path: str) -> VerificationResult:
        """Verify Python file has valid syntax."""
        full_path = Path(path)
        if not full_path.is_absolute():
            full_path = self.workspace / path
        
        if not full_path.exists():
            return VerificationResult(
                check_name="python_syntax",
                status=VerificationStatus.FAILED,
                expected="File exists",
                actual="File not found",
                message=f"VERIFICATION FAILED: File not found: {path}",
            )
        
        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile", str(full_path)],
                capture_output=True,
                text=True,
            )
            
            if result.returncode != 0:
                return VerificationResult(
                    check_name="python_syntax",
                    status=VerificationStatus.FAILED,
                    expected="Valid Python syntax",
                    actual=result.stderr,
                    message=f"VERIFICATION FAILED: Syntax error in {path}",
                )
            
            return VerificationResult(
                check_name="python_syntax",
                status=VerificationStatus.PASSED,
                expected="Valid Python syntax",
                actual="Syntax OK",
                message=f"✓ Python syntax valid: {path}",
            )
            
        except Exception as e:
            return VerificationResult(
                check_name="python_syntax",
                status=VerificationStatus.ERROR,
                expected="Syntax check",
                actual=str(e),
                message=f"VERIFICATION ERROR: {e}",
            )
    
    def verify_tests_pass(
        self,
        test_command: str = "pytest",
        test_path: str | None = None,
    ) -> VerificationResult:
        """Verify tests pass."""
        cmd = [test_command]
        if test_path:
            cmd.append(test_path)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=300,  # 5 min timeout
            )
            
            if result.returncode != 0:
                # Extract failure info
                failure_info = result.stdout[-500:] if result.stdout else result.stderr[-500:]
                return VerificationResult(
                    check_name="tests_pass",
                    status=VerificationStatus.FAILED,
                    expected="All tests pass",
                    actual=f"Exit code {result.returncode}",
                    message=f"VERIFICATION FAILED: Tests failed\n{failure_info}",
                )
            
            return VerificationResult(
                check_name="tests_pass",
                status=VerificationStatus.PASSED,
                expected="All tests pass",
                actual="Tests passed",
                message=f"✓ All tests pass",
            )
            
        except subprocess.TimeoutExpired:
            return VerificationResult(
                check_name="tests_pass",
                status=VerificationStatus.ERROR,
                expected="Tests complete",
                actual="Timeout",
                message="VERIFICATION ERROR: Tests timed out",
            )
        except Exception as e:
            return VerificationResult(
                check_name="tests_pass",
                status=VerificationStatus.ERROR,
                expected="Tests run",
                actual=str(e),
                message=f"VERIFICATION ERROR: {e}",
            )
    
    # ═══════════════════════════════════════════════════════════════════════════
    # COMPOSITE VERIFICATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def verify_or_fail(
        self,
        tool_name: str,
        verifications: list[VerificationResult],
        command: str | None = None,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        duration_ms: float = 0.0,
        evidence: dict | None = None,
    ) -> ToolExecutionResult:
        """
        The main verification gate.
        
        RULE: All verifications must pass for success.
        Any failure = tool execution failed, regardless of what the model claims.
        """
        all_passed = all(v.status == VerificationStatus.PASSED for v in verifications)
        
        # Determine failure reason if any
        failure_reason = None
        if not all_passed:
            failed = [v for v in verifications if v.status != VerificationStatus.PASSED]
            failure_reason = "; ".join(v.message for v in failed)
        
        result = ToolExecutionResult(
            tool_name=tool_name,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            verifications=verifications,
            all_passed=all_passed,
            success=all_passed,
            failure_reason=failure_reason,
            evidence=evidence or {},
        )
        
        # Log for audit
        self.verification_log.append(result)
        
        return result
    
    def create_file_with_verification(
        self,
        path: str,
        content: str,
    ) -> ToolExecutionResult:
        """
        Create a file and verify it was actually created.
        
        This is how file creation SHOULD work - with verification.
        """
        start_time = datetime.utcnow()
        full_path = Path(path)
        if not full_path.is_absolute():
            full_path = self.workspace / path
        
        verifications = []
        stdout = ""
        stderr = ""
        
        try:
            # Ensure parent directory exists
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the file
            full_path.write_text(content)
            stdout = f"Wrote {len(content)} bytes to {path}"
            
        except Exception as e:
            stderr = str(e)
            verifications.append(VerificationResult(
                check_name="write_file",
                status=VerificationStatus.FAILED,
                expected="File written",
                actual=str(e),
                message=f"VERIFICATION FAILED: Could not write file: {e}",
            ))
        
        # Now verify it actually exists
        verifications.append(self.verify_file_created(str(full_path), min_size=1))
        
        # Verify content matches
        if full_path.exists():
            actual_content = full_path.read_text()
            if actual_content == content:
                verifications.append(VerificationResult(
                    check_name="content_match",
                    status=VerificationStatus.PASSED,
                    expected=f"Content: {len(content)} bytes",
                    actual=f"Content: {len(actual_content)} bytes",
                    message="✓ Content verified",
                ))
            else:
                verifications.append(VerificationResult(
                    check_name="content_match",
                    status=VerificationStatus.FAILED,
                    expected=f"Content: {len(content)} bytes",
                    actual=f"Content: {len(actual_content)} bytes (MISMATCH)",
                    message="VERIFICATION FAILED: Content mismatch after write",
                ))
        
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return self.verify_or_fail(
            tool_name="create_file",
            verifications=verifications,
            command=f"write({path})",
            exit_code=0 if all(v.status == VerificationStatus.PASSED for v in verifications) else 1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            evidence={
                "path": str(full_path),
                "size": len(content),
                "hash": hashlib.sha256(content.encode()).hexdigest()[:16],
            },
        )
    
    def run_command_with_verification(
        self,
        command: str,
        expected_files: list[str] | None = None,
        check_syntax: list[str] | None = None,
        run_tests: bool = False,
    ) -> ToolExecutionResult:
        """
        Run a command and verify its effects.
        
        This is how command execution SHOULD work - with verification.
        """
        start_time = datetime.utcnow()
        verifications = []
        
        # F1 hardening (defense in depth): even though this path uses shell=True
        # for legitimate shell features, no command may run if it matches a Law-0
        # absolute block. Untrusted input that somehow reached here still cannot
        # execute a destructive command.
        import re as _re
        from ..governance.bylaws import BLOCKED_PATTERNS as _BLOCKS
        for _pat, _reason in _BLOCKS:
            if _re.search(_pat, command):
                return ToolExecutionResult(
                    tool_name="run_command",
                    command=command,
                    exit_code=126,
                    stdout="",
                    stderr=f"BLOCKED by Law 0: {_reason}",
                    duration_ms=0.0,
                    verifications=[],
                    all_passed=False,
                    success=False,
                    failure_reason=f"Law 0 block: {_reason}",
                    evidence={"blocked": True, "reason": _reason, "pattern": _pat},
                )

        # Run the command
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=120,
            )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired:
            exit_code = -1
            stdout = ""
            stderr = "Command timed out"
        except Exception as e:
            exit_code = -1
            stdout = ""
            stderr = str(e)
        
        # Verify exit code
        verifications.append(self.verify_command_success(exit_code))
        
        # Verify no errors in output
        verifications.append(self.verify_no_errors_in_output(stdout, stderr))
        
        # Verify expected files were created/modified
        if expected_files:
            for file_path in expected_files:
                verifications.append(self.verify_file_created(file_path))
        
        # Check Python syntax
        if check_syntax:
            for file_path in check_syntax:
                verifications.append(self.verify_python_syntax(file_path))
        
        # Run tests if requested
        if run_tests:
            verifications.append(self.verify_tests_pass())
        
        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return self.verify_or_fail(
            tool_name="run_command",
            verifications=verifications,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            evidence={
                "command": command,
                "exit_code": exit_code,
            },
        )


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION WITH BYLAWS
# ═══════════════════════════════════════════════════════════════════════════════

def verification_required(func: Callable) -> Callable:
    """
    Decorator that enforces verification for tool functions.
    
    Usage:
        @verification_required
        def create_file(path, content):
            ...
    """
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        
        # If result is a ToolExecutionResult, check it passed
        if isinstance(result, ToolExecutionResult):
            if not result.success:
                raise VerificationError(
                    f"Tool '{result.tool_name}' failed verification: {result.failure_reason}"
                )
        
        return result
    
    return wrapper


class VerificationError(Exception):
    """Raised when a tool execution fails verification."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# EXAMPLE USAGE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    verifier = ToolVerifier(workspace="/tmp/test_workspace")
    
    # Create workspace
    os.makedirs("/tmp/test_workspace", exist_ok=True)
    
    # Test 1: Create a file with verification
    print("=" * 60)
    print("TEST 1: Create file with verification")
    print("=" * 60)
    
    result = verifier.create_file_with_verification(
        path="test.py",
        content="print('Hello, World!')\n",
    )
    
    print(f"Success: {result.success}")
    for v in result.verifications:
        print(f"  {v.status.value}: {v.message}")
    
    # Test 2: Run a command that should succeed
    print("\n" + "=" * 60)
    print("TEST 2: Run successful command")
    print("=" * 60)
    
    result = verifier.run_command_with_verification(
        command="python3 test.py",
        check_syntax=["test.py"],
    )
    
    print(f"Success: {result.success}")
    print(f"Stdout: {result.stdout}")
    for v in result.verifications:
        print(f"  {v.status.value}: {v.message}")
    
    # Test 3: Try to verify a file that doesn't exist
    print("\n" + "=" * 60)
    print("TEST 3: Verify non-existent file (should fail)")
    print("=" * 60)
    
    check = verifier.verify_file_created("does_not_exist.py")
    print(f"Status: {check.status.value}")
    print(f"Message: {check.message}")
