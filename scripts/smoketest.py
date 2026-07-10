#!/usr/bin/env python3
"""
AgentGRIT Smoketest

Verifies router and bylaws work correctly with logging.
Run: make agentgrit-smoketest
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from src.execution.router import LLMRouter, classify_task, PROVIDER_CAPABILITIES
    from src.governance.bylaws import (
        BylawEngine,
        AgentRole,
        get_bylaw_engine,
        get_observer_engine,
    )
except ImportError as e:
    print(f"Import error: {e}")
    print("\nRun via Makefile (sets PYTHONPATH correctly):")
    print("  make agentgrit-smoketest")
    sys.exit(1)


def write_jsonl(filepath: Path, entry: dict):
    """Append JSON line to log file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "a") as f:
        f.write(json.dumps(entry) + "\n")


def test_router():
    """Test capability-based router."""
    print("\n[1] Testing capability-based router...")

    router = LLMRouter()
    task = "Research the latest FastAPI release notes and changelog"

    decision = router.route_with_evidence(task)

    print(f"    Task: \"{task}\"")
    print(f"    Provider: {decision.provider}")
    print(f"    Category: {decision.category.value}")
    print(f"    Confidence: {decision.confidence}")
    print(f"    Capabilities: {decision.required_capabilities}")
    print(f"    Reason: {decision.reason}")

    # Log to file
    log_entry = decision.to_log_entry()
    log_entry["test"] = "smoketest"
    log_entry["task"] = task
    write_jsonl(Path("logs/router.jsonl"), log_entry)

    # Verify routing is correct (web_search → perplexity)
    assert decision.provider == "perplexity", f"Expected perplexity, got {decision.provider}"
    assert "web_search" in decision.required_capabilities

    print("    ✅ Router working")
    return True


def test_bylaws_blocking():
    """Test bylaw engine blocks dangerous commands."""
    print("\n[2] Testing bylaw engine (developer role)...")

    engine = get_bylaw_engine(AgentRole.DEVELOPER)
    command = "rm -rf /"

    result = engine.evaluate(command, action_type="bash")

    print(f"    Command: \"{command}\"")
    print(f"    Action: {result.action.value}")
    print(f"    Reason: {result.reason}")

    # Log to file
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "test": "smoketest",
        "command": command,
        "action": result.action.value,
        "reason": result.reason,
        "role": "developer",
    }
    write_jsonl(Path("logs/bylaws.jsonl"), log_entry)

    # Verify blocking works
    assert result.action.value == "block", f"Expected block, got {result.action.value}"

    print("    ✅ Bylaws blocking dangerous commands")
    return True


def test_role_capability():
    """Test role-based capability enforcement."""
    print("\n[3] Testing role-based capability check...")

    engine = get_observer_engine()  # Observer cannot execute bash
    command = "echo hello"

    result = engine.evaluate(command, action_type="bash")

    print(f"    Role: observer")
    print(f"    Action: bash")
    print(f"    Result: {result.action.value} ({result.reason})")

    # Log to file
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "test": "smoketest",
        "command": command,
        "action": result.action.value,
        "reason": result.reason,
        "role": "observer",
    }
    write_jsonl(Path("logs/bylaws.jsonl"), log_entry)

    # Verify observer cannot bash
    assert result.action.value == "block", f"Expected block, got {result.action.value}"
    assert "cannot perform bash" in result.reason.lower()

    print("    ✅ Role enforcement working")
    return True


def test_router_cost_first():
    """Test cost-first routing (simple task → ollama)."""
    print("\n[4] Testing cost-first routing (simple → Ollama)...")

    router = LLMRouter()
    task = "Format this Python code nicely"

    decision = router.route_with_evidence(task)

    print(f"    Task: \"{task}\"")
    print(f"    Provider: {decision.provider}")
    print(f"    Capabilities: {decision.required_capabilities}")

    # Log to file
    log_entry = decision.to_log_entry()
    log_entry["test"] = "smoketest"
    log_entry["task"] = task
    write_jsonl(Path("logs/router.jsonl"), log_entry)

    # Simple task should go to Ollama (free)
    assert decision.provider == "ollama", f"Expected ollama, got {decision.provider}"

    print("    ✅ Cost-first routing working")
    return True


def test_persona_selection():
    """Test 5-Element Persona Framework selection."""
    print("\n[5] Testing persona selection (5-Element Framework)...")

    from src.governance.personas import select_persona, get_persona_prompt, PERSONA_LIBRARY

    # Test 1: Architecture task should match backend_architect
    task = "Design the architecture for multi-LLM routing and orchestration"
    persona = select_persona(task)

    print(f"    Task: \"{task[:50]}...\"")
    print(f"    Persona: {persona.id if persona else 'None'}")

    assert persona is not None, "Should match backend_architect persona"
    assert persona.id == "backend_architect", f"Expected backend_architect, got {persona.id}"

    # Test 2: Simple task should NOT match a persona
    simple_task = "Format this code"
    simple_persona = select_persona(simple_task)

    print(f"    Simple task: \"{simple_task}\"")
    print(f"    Persona: {simple_persona.id if simple_persona else 'None (correct)'}")

    assert simple_persona is None, "Simple task should not match a persona"

    # Test 3: Persona prompt generation for Claude
    prompt = get_persona_prompt(task, "claude-sonnet")
    assert len(prompt) > 100, "Full persona prompt should be substantial"
    assert "architect" in prompt.lower() or "orchestration" in prompt.lower(), "Prompt should contain persona content"

    # Test 4: No persona for Ollama
    ollama_prompt = get_persona_prompt(task, "ollama")
    assert ollama_prompt == "", "Ollama should not get persona prefix"

    print("    ✅ Persona selection working")
    return True


def test_persona_bylaw():
    """Test PersonaBylaw soft enforcement."""
    print("\n[6] Testing persona bylaw (soft enforcement)...")

    from src.governance.bylaws import check_persona_bylaw, BylawAction

    # Complex task without persona should NOTIFY
    result = check_persona_bylaw("architecture", has_persona=False)
    print(f"    architecture + no persona: {result.action.value}")
    assert result.action == BylawAction.NOTIFY, "Should notify for complex task without persona"

    # Complex task with persona should PROCEED
    result2 = check_persona_bylaw("architecture", has_persona=True)
    print(f"    architecture + has persona: {result2.action.value}")
    assert result2.action == BylawAction.PROCEED, "Should proceed with persona"

    # Simple task without persona should PROCEED (no persona needed)
    result3 = check_persona_bylaw("simple_code", has_persona=False)
    print(f"    simple_code + no persona: {result3.action.value}")
    assert result3.action == BylawAction.PROCEED, "Simple task doesn't need persona"

    print("    ✅ Persona bylaw working")
    return True


def test_bylaws_wired_into_execute():
    """Test that router.execute() actually calls the bylaws gate before
    dispatch — not just that bylaws.py works when called directly (that
    was already covered by test_bylaws_blocking). This is the wiring
    check: a dangerous task must never reach a model call at all."""
    print("\n[7] Testing bylaws gate wired into router.execute()...")

    async def _run():
        router = LLMRouter()
        result = await router.execute("Run this command: rm -rf / --no-preserve-root")
        return result

    result = asyncio.run(_run())
    print(f"    Task: dangerous rm -rf command via execute()")
    print(f"    Provider: {result['provider']}")
    print(f"    Bylaw action: {result.get('bylaw_action', 'N/A')}")

    assert result["provider"] == "bylaws", f"Expected bylaws to intercept, got provider={result['provider']}"
    assert result.get("bylaw_action") == "block", f"Expected block, got {result.get('bylaw_action')}"
    print("    ✅ bylaws gate wired into execute() — dangerous task never reached a model")
    return True


def test_model_provenance_gate():
    """Test the provenance registry directly, and confirm _call_ollama
    refuses a forbidden model before making any network call."""
    print("\n[8] Testing model provenance gate...")
    from src.governance.model_provenance import is_model_approved, explain

    assert is_model_approved("gemma4:12b") is True, "gemma4:12b should be approved"
    assert is_model_approved("qwen3-coder:30b") is False, "qwen3-coder:30b should be forbidden"
    assert is_model_approved("glm-4.7-flash:latest") is False, "glm-4.7-flash should be forbidden"
    assert is_model_approved("blendmodel:9b") is False, "blendmodel:9b should be forbidden (mixed external lineage)"
    assert is_model_approved("totally-unknown-model:1b") is False, "unregistered models default to forbidden"
    print(f"    gemma4:12b: approved")
    print(f"    qwen3-coder:30b: {explain('qwen3-coder:30b')}")

    async def _run():
        router = LLMRouter(config={"ollama_model": "qwen3-coder:30b"})
        return await router._call_ollama("test prompt")

    response, tokens = asyncio.run(_run())
    print(f"    _call_ollama with forbidden model -> {response[:80]}")
    assert "Blocked by provenance policy" in response, "Forbidden model should be blocked before network call"
    assert tokens == 0
    print("    ✅ Provenance gate blocks forbidden models before any network call")
    return True


def test_identity_prompt_live():
    """Test that the identity layer renders real live state without
    crashing, and that it's actually a supplement (bylaws still gates
    independently — see test_bylaws_wired_into_execute)."""
    print("\n[9] Testing live identity prompt assembly...")
    from src.governance.identity import build_identity_prompt

    prompt = build_identity_prompt("simple_code")
    assert "AGENTGRIT OPERATING IDENTITY" in prompt
    assert "Trust level:" in prompt
    assert "STOP" in prompt  # escalation checklist present
    print(f"    Prompt length: {len(prompt)} chars")
    print("    ✅ Identity prompt renders from live trust/bylaws state")
    return True


def main():
    print("AgentGRIT Smoketest")
    print("=" * 20)

    tests = [
        test_router,
        test_bylaws_blocking,
        test_role_capability,
        test_router_cost_first,
        test_persona_selection,
        test_persona_bylaw,
        test_bylaws_wired_into_execute,
        test_model_provenance_gate,
        test_identity_prompt_live,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"    ❌ FAILED: {e}")
            failed += 1

    print("\n" + "=" * 40)
    print(f"\nLogs written to:")
    print(f"  - logs/router.jsonl")
    print(f"  - logs/bylaws.jsonl")
    print(f"\n{passed} passed, {failed} failed")

    if failed > 0:
        print("\n❌ Some tests failed")
        sys.exit(1)
    else:
        print("\n✅ All tests passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
