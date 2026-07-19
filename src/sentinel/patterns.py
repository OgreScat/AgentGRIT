"""Sentinel pattern sets. Generic classes only — a public repo must never
enumerate private vocabulary (the sweeper-is-the-leak lesson)."""
from __future__ import annotations

import re

# BLOCK — presence alone is disqualifying
BLOCK_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("secret.generic", re.compile(r"sk-[A-Za-z0-9]{20,}"), "secret-shaped token"),
    ("secret.aws", re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    ("secret.github", re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub token"),
    ("secret.slack", re.compile(r"xox[bp]-[A-Za-z0-9-]{10,}"), "Slack token"),
    ("secret.pem", re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PGP) PRIVATE KEY-----"), "private key material"),
    ("destroy.rmrf", re.compile(r"\brm\s+-rf\s+/(?:\s|$|\*)"), "filesystem-root destruction"),
    ("supply.pipe_shell", re.compile(r"(?:curl|wget)[^\n|]*\|\s*(?:ba)?sh\b"), "pipe-to-shell install"),
]

# HOLD — needs human/owner review before any authority
HOLD_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("code.eval", re.compile(r"\beval\s*\("), "dynamic eval"),
    ("code.exec", re.compile(r"\bexec\s*\("), "dynamic exec"),
    ("code.shell_true", re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True"), "shell=True subprocess"),
    ("code.os_system", re.compile(r"\bos\.system\s*\("), "os.system call"),
    ("code.pickle", re.compile(r"\bpickle\.loads?\s*\("), "pickle deserialization"),
    ("code.dynimport", re.compile(r"__import__\s*\("), "dynamic import"),
    ("inject.ignore", re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.I), "prompt-injection marker"),
    ("inject.system", re.compile(r"disregard\s+(?:the\s+)?system\s+prompt", re.I), "prompt-injection marker"),
    ("inject.newrole", re.compile(r"you\s+are\s+now\s+(?:in\s+)?(?:developer|jailbreak|dan)\b", re.I), "role-override marker"),
]

# LIMIT — allowed with constraints; surfaced, never silent
LIMIT_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("net.egress", re.compile(r"https?://(?!localhost|127\.0\.0\.1)[a-z0-9.-]+", re.I), "external network egress"),
    ("perm.wildcard", re.compile(r"[\"\']permissions[\"\']\s*:\s*\[?\s*[\"\']\*"), "wildcard permission grant"),
    ("cred.env_broad", re.compile(r"os\.environ(?!\.get\()\b"), "broad environment access"),
]

SCAN_SUFFIXES = {".py", ".js", ".ts", ".sh", ".md", ".txt", ".json", ".yaml", ".yml",
                 ".toml", ".cfg", ".ini", ".html", ".css", ""}
