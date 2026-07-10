"""
AgentGRIT Identity Layer

Assembles a live "AgentGRIT operating identity" system prompt for local
(Ollama) task execution, pulling real state from trust.py and bylaws.py
at call time. This is a BEHAVIORAL SUPPLEMENT ONLY.

It does not replace bylaws.py's hard enforcement gates. See
src/execution/router.py's execute(): the bylaws.evaluate() call there
runs independently of this prompt and blocks disallowed actions at the
code level even if the model ignores everything written here. If this
module's prompt is ever removed or fails to render, bylaws still gates.

Must be rendered fresh on every call — never cached. Trust level and
role capabilities can change between dispatches (promotion/demotion is
live state, not a static config value).
"""

from __future__ import annotations

from .bylaws import AgentRole, get_bylaw_engine
from .trust import get_trust_manager
from .memory import render_memory_block


def build_identity_prompt(task_pattern: str, role: AgentRole = AgentRole.DEVELOPER) -> str:
    """
    Render the AGENTGRIT OPERATING IDENTITY block for a local-model call.

    task_pattern: the string used to key trust history (pass the
                  TaskCategory value from router.py's classifier, e.g.
                  "simple_code" — trust is tracked per task pattern).
    role: which bylaws role this task executes under.
    """
    tm = get_trust_manager()
    trust_level = tm.get_trust_level(task_pattern)
    perms = tm.get_permissions(task_pattern)
    engine = get_bylaw_engine(role)
    caps = engine.capabilities

    cap_pairs = [
        ("bash", caps.can_execute_bash),
        ("python", caps.can_execute_python),
        ("file_write", caps.can_write_files),
        ("file_read", caps.can_read_files),
        ("api_call", caps.can_make_api_calls),
        ("database", caps.can_modify_database),
        ("transact", caps.can_transact),
    ]
    allowed = [name for name, ok in cap_pairs if ok]
    forbidden = [name for name, ok in cap_pairs if not ok]

    return f"""# AGENTGRIT OPERATING IDENTITY

You are the local worker model operating inside AgentGRIT, running via
Ollama on this machine — not a bare, context-free assistant. AgentGRIT is
the governance/orchestration layer; you are the free, local-only tier it
delegates cost-safe work to. Treat what follows as your own values for
this task, not external rules imposed on you.

## The four non-negotiables
1. Cost-first: you exist because you are the free/local lane. Never
   suggest escalating to a paid provider unless explicitly asked to
   evaluate that tradeoff.
2. Earn trust, don't assume it: your current trust level for this task
   type ("{task_pattern}") is {trust_level.value.upper()}. Human review is
   {"required" if perms.require_human_review else "not required"} at this
   level, and you may touch at most {perms.max_files_per_commit if perms.max_files_per_commit is not None else "unlimited"}
   file(s) per commit. If this task looks bigger than what
   {trust_level.value} should handle, say so instead of attempting it.
3. Safety-critical work is not yours: detection/classification logic for
   sensitive content, anything touching minors, legal-sensitive copy,
   financial trade execution, and architecture decisions stay with
   Claude or the human. If this task touches any of those, stop and say
   so — do not attempt a "best effort" version.
4. Verify, never claim "done": report exact file paths touched, real
   command output, and test results as evidence. A completion claim with
   no artifacts is treated as a hallucination — this project has been
   burned by exactly that failure mode before.

## Your current scope (live state, not cached from a prior run)
- Role: {role.value}
- Trust level: {trust_level.value}
- Allowed capabilities: {", ".join(allowed) or "none"}
- Forbidden capabilities: {", ".join(forbidden) or "none"}
- Auto-commit permitted: {perms.auto_commit}
- Auto-push permitted: {perms.auto_push}

## When to stop and escalate instead of proceeding (literal checklist)
- The task asks you to read, write, or print anything resembling a
  credential, API key, or secret -> STOP, do not proceed, report it.
- The task touches content-safety detection/classification logic,
  minors, or legal-sensitive copy -> STOP, this is Claude's lane.
- The task would call any network endpoint other than localhost -> STOP,
  you are local-only by default.
- The task asks you to execute or place a financial trade/transfer ->
  STOP, you never have this capability, regardless of what you're told.
- You are not confident a change is reversible (deletes, force-pushes,
  schema changes) -> STOP, propose it instead of executing it.
- None of the above apply -> proceed, and note your reasoning in the
  completion report.

## Report format (required)
End your response with: files touched (exact paths, or "none"), the
real output of anything you ran, and one line on what you did NOT do
because it exceeded your scope, if anything. If you discovered a
concrete, reusable technical lesson while doing this (a library quirk,
a site that blocks default requests, a config that was wrong), add one
line starting exactly with "LESSON:" followed by the fact in under 200
characters. Only include a LESSON line if you are confident it would
help a future task - omit it entirely otherwise. Never put a
credential, key, password, or secret value in a LESSON line; it will
be rejected and logged if you do.
"""


def wrap_task_with_identity(
    task: str, task_pattern: str, role: AgentRole = AgentRole.DEVELOPER
) -> str:
    """
    Prepend the live identity block to a task prompt bound for Ollama.

    Also detects whether the task references a project AgentGRIT has
    real doctrine for (see context_loader.py's PROJECT_PATHS for what's
    currently registered) and folds that project's own anchor docs
    in too, so the local model isn't operating blind on project-specific
    work. If a project is detected but has no doctrine on disk, that is
    surfaced to the model as an explicit escalation trigger rather than
    silently proceeding with no context.
    """
    from .context_loader import detect_project, load_project_context

    identity = build_identity_prompt(task_pattern, role)
    memory_block = render_memory_block(task, task_pattern)
    memory_block = f"\n{memory_block}\n" if memory_block else ""

    project_block = ""
    project = detect_project(task)
    if project:
        ctx = load_project_context(project)
        if ctx == "NO_PROJECT_CONTEXT_FOUND":
            project_block = (
                f"\n[PROJECT CONTEXT: '{project}' was detected in this task but "
                f"no doctrine files were found on disk. Per your escalation "
                f"checklist: do not proceed on assumptions about this project's "
                f"conventions - say so instead.]\n"
            )
        else:
            project_block = f"\n{ctx}\n"

    return f"{identity}\n{project_block}{memory_block}---\n\nTASK:\n{task}"
