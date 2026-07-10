"""Template agent -- the starting point for your own AgentGRIT agent.

This is deliberately a skeleton, not a real product. Copy this file, give
it your own name, and fill in run_once(). What you get for free just by
extending this pattern:

- Your persona's voice (via governance.persona.render_persona_block),
  bounded by the AgentGRIT constitution that persona can't opt out of.
- Bylaws gating on every action (governance.bylaws.get_bylaw_engine) --
  BLOCK/ESCALATE/NOTIFY/VERIFY_FIRST/PROCEED decided the same way for you
  as for every other agent in the framework.
- An evidence-bundle report instead of a bare claim: what you did, the
  command you ran, and its actual output -- never "done" without proof.

Register your agent's name in src/main.py's AgentOrchestrator.AVAILABLE_AGENTS
when you're ready to run it as a background service.
"""

# Lives in src/agents/ alongside every other agent -- same relative-import
# convention the rest of this package already uses (see governance/*.py).

from __future__ import annotations

from ..governance.bylaws import get_bylaw_engine, AgentRole, BylawAction
from ..governance.persona import render_persona_block


class TemplateAgent:
    """Copy me. Rename me. Give me a real job."""

    def __init__(self, project_key: str | None = None):
        self.project_key = project_key
        self.bylaws = get_bylaw_engine(AgentRole.DEVELOPER)

    def build_prompt(self, task: str) -> str:
        """Combine your project's persona (if registered) with the task."""
        persona_block = render_persona_block(self.project_key)
        return f"{persona_block}\n\n---\n\nTASK: {task}"

    async def run_once(self, task: str) -> dict:
        """
        Do one unit of real work and return an evidence bundle. Replace the
        body of this method -- everything above it (persona + bylaws) is
        the part you don't have to rebuild.
        """
        # Every real action should be checked against the bylaws before it
        # happens, not after:
        result = self.bylaws.evaluate(command=task, action_type="bash")
        if result.action == BylawAction.BLOCK:
            return {"status": "blocked", "reason": result.reason}
        if result.action == BylawAction.ESCALATE:
            return {"status": "escalate", "reason": result.reason}

        prompt = self.build_prompt(task)

        # TODO: replace this with your actual work -- call your model,
        # run your tool, do the thing this agent exists for.
        output = f"[TemplateAgent] would act on: {prompt[:120]}..."

        return {
            "status": "done",
            "evidence": {
                "task": task,
                "output": output,
            },
        }
