#!/usr/bin/env python3
"""
AgentGRIT Import Regression Test

Verifies all core modules can be imported without errors.
Run: make test-imports

This catches import regressions early - if this fails, the package
structure is broken and nothing will work.
"""

import sys


def test_imports():
    """Test that all core modules import correctly."""
    print("AgentGRIT Import Test")
    print("=" * 40)

    modules = [
        ("src.utils.logging", "Logging utilities"),
        ("src.execution.router", "LLM Router"),
        ("src.governance.bylaws", "Bylaws engine"),
        ("src.governance.personas", "Persona framework"),
    ]

    passed = 0
    failed = 0

    for module_name, description in modules:
        try:
            __import__(module_name)
            print(f"  [OK] {module_name}")
            passed += 1
        except ImportError as e:
            print(f"  [FAIL] {module_name}: {e}")
            failed += 1

    print()
    print("=" * 40)

    # Test specific imports work
    print("\nTesting specific exports...")

    specific_imports = [
        ("src.utils.logging", ["log_routing_decision", "log_bylaw_decision", "log_heartbeat"]),
        ("src.execution.router", ["LLMRouter", "classify_task", "PROVIDER_CAPABILITIES"]),
        ("src.governance.bylaws", ["BylawEngine", "AgentRole", "get_observer_engine", "check_persona_bylaw"]),
        ("src.governance.personas", ["select_persona", "get_persona_prompt", "PERSONA_LIBRARY"]),
    ]

    for module_name, names in specific_imports:
        try:
            module = __import__(module_name, fromlist=names)
            for name in names:
                if not hasattr(module, name):
                    print(f"  [FAIL] {module_name}.{name} not found")
                    failed += 1
                else:
                    passed += 1
        except Exception as e:
            print(f"  [FAIL] {module_name}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")

    if failed > 0:
        print("\n[FAIL] Import test failed")
        print("\nEnsure you run via Makefile:")
        print("  make test-imports")
        sys.exit(1)
    else:
        print("\n[OK] All imports working")
        sys.exit(0)


if __name__ == "__main__":
    test_imports()
