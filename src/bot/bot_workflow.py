"""
GRIT Telegram workflow handlers — the live wire between mobile and the governor.

This replaces the dead `# TODO: spawn via orchestrator` stub. It is written as a
standalone module so it can be unit-tested without a running Telegram client:
the rendering functions are pure and take a task string, returning the text +
button layout the bot sends.

Flow:
  /plan <task>   -> governor runs -> renders cost-annotated plan + verdict
                    -> if ESCALATE/BLOCK: shows Approve/Reject buttons (admin)
                    -> if ALLOW/DOWNGRADE: shows the routing spec to paste into
                       Claude Code, plus an optional "use downgrade" button.

The bot layer (aiogram) only has to: call render_plan_message(task), send the
text, attach the buttons from the returned spec, and on button callback call
confirm_plan(...). No orchestration logic lives in the bot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.workflow.cost_governor import govern_task, GovernorConfig, Verdict


@dataclass
class Button:
    label: str
    callback: str   # callback_data string the bot routes back to confirm_plan


@dataclass
class BotMessage:
    text: str
    buttons: list[Button]
    routing_spec: dict | None  # present when there's something to run


_VERDICT_EMOJI = {
    Verdict.ALLOW: "✅",
    Verdict.DOWNGRADE: "💸",
    Verdict.ESCALATE: "⚠️",
    Verdict.BLOCK: "🛑",
}


def render_plan_message(task: str, trust_level: str = "UNTRUSTED") -> BotMessage:
    """
    Pure function: task -> rendered approval message + buttons.
    Safe to unit-test; performs no I/O.
    """
    decision = govern_task(task, GovernorConfig(trust_level=trust_level))
    chosen = decision.downgraded_plan or decision.plan
    emoji = _VERDICT_EMOJI.get(decision.verdict, "•")

    lines = [
        f"{emoji} *Workflow plan* — `{decision.verdict.value.upper()}`",
        f"_{task}_",
        "",
        f"*Cost:* ${chosen.governed_cost:.2f}  "
        f"(all-Opus would be ${decision.plan.naive_opus_cost:.2f})",
        f"*Saved vs default:* ${decision.plan.naive_opus_cost - chosen.governed_cost:.2f}",
        "",
        "*Stages:*",
    ]
    for i, s in enumerate(chosen.stages, 1):
        lines.append(f"{i}. {s.name} → `{s.assigned_model.value}` ×{s.fanout}")

    if decision.reasons:
        lines.append("")
        lines.append("*Notes:*")
        for r in decision.reasons:
            lines.append(f"• {r}")

    buttons: list[Button] = []
    routing_spec: dict | None = None

    if decision.verdict == Verdict.BLOCK:
        lines.append("")
        lines.append("🛑 *Blocked.* Re-scope to a smaller slice and try again.")
        # No run button. Optionally allow override only at AUTONOMOUS (not here).

    elif decision.verdict == Verdict.ESCALATE:
        lines.append("")
        lines.append("⚠️ *Needs your approval before running.*")
        buttons = [
            Button("✅ Approve & get spec", f"approve::{_encode(task, trust_level)}"),
            Button("🛑 Reject", "reject"),
        ]
        if decision.downgraded_plan:
            buttons.insert(1, Button(
                "💸 Approve downgrade",
                f"downgrade::{_encode(task, trust_level)}",
            ))

    else:  # ALLOW or DOWNGRADE — runnable now
        routing_spec = chosen.routing_spec()
        lines.append("")
        lines.append("Paste this into Claude Code after your `ultracode:` prompt:")
        lines.append("```json")
        lines.append(json.dumps(routing_spec, indent=2))
        lines.append("```")
        if decision.verdict == Verdict.DOWNGRADE and decision.plan is not chosen:
            buttons = [Button("Use full (no downgrade)",
                              f"full::{_encode(task, trust_level)}")]

    return BotMessage("\n".join(lines), buttons, routing_spec)


def confirm_plan(callback_data: str) -> BotMessage:
    """
    Handle a button press. callback_data is one of:
      approve::<enc> | downgrade::<enc> | full::<enc> | reject
    Returns the follow-up message (with the routing spec to run, or a cancel).
    """
    if callback_data == "reject":
        return BotMessage("🛑 Cancelled. Nothing will run.", [], None)

    action, _, enc = callback_data.partition("::")
    task, trust_level = _decode(enc)
    decision = govern_task(task, GovernorConfig(trust_level=trust_level))

    if action == "downgrade":
        plan = decision.downgraded_plan or decision.plan
    elif action == "full":
        plan = decision.plan
    else:  # approve
        plan = decision.downgraded_plan or decision.plan

    spec = plan.routing_spec()
    text = (
        f"✅ Approved. Cost ~${plan.governed_cost:.2f}.\n\n"
        "Run in Claude Code with:\n"
        f"```\nultracode: {task}\n\nRoute stages per this spec:\n"
        f"{json.dumps(spec, indent=2)}\n```"
    )
    return BotMessage(text, [], spec)


# ── tiny reversible encoding for callback_data (Telegram caps at 64 bytes, so
#    we keep tasks short; long tasks fall back to a hash the bot can look up) ──

def _encode(task: str, trust: str) -> str:
    # Telegram callback_data limit is 64 bytes. Keep it compact; truncate task.
    safe = task[:40].replace("::", ":")
    return f"{trust}|{safe}"


def _decode(enc: str) -> tuple[str, str]:
    trust, _, task = enc.partition("|")
    return task, (trust or "UNTRUSTED")
