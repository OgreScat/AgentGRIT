"""AgentGRIT Persona Layer

Every persona an AgentGRIT user defines inherits a fixed floor: the
AgentGRIT constitution (bylaws, trust ladder, evidence-over-claims, and the
Zeroth Law -- see governance/bylaws.py). A persona adds voice and
characteristics on top of that floor; it can never reason its way out from
under it. A persona that could override its own guardrails would defeat the
point of having guardrails.

This file ships with an empty persona registry on purpose. AgentGRIT does
not come with opinions about what you're building -- only about how you
build it. Copy TEMPLATE below, fill in your own project, and register it
in SOULS.
"""

from __future__ import annotations

from dataclasses import dataclass


AGENTGRIT_CONSTITUTION = (
    "Every persona operates under AgentGRIT's bylaws without exception: "
    "evidence over claims, no self-graded homework, escalate rather than "
    "guess on real risk, and the Zeroth Law -- a real, foreseeable harm "
    "does not go unreported just because nobody asked about it. A "
    "persona's voice and values sit on top of this floor. They never "
    "replace it."
)


@dataclass(frozen=True)
class Persona:
    """One voice inside a project's soul."""

    name: str
    role: str
    voice: str
    values: str
    grounded_in: str


@dataclass(frozen=True)
class ProjectSoul:
    """A project's full persona set, plus how they collaborate (if more than one)."""

    project_key: str
    display_name: str
    personas: tuple[Persona, ...]
    collaboration: str = ""
    agentgrit_mandate: str = AGENTGRIT_CONSTITUTION


# -----------------------------------------------------------------------
# TEMPLATE -- copy this, fill in your own project. Add as many personas as
# your project actually needs; a single solo persona is correct if your
# project's job is fidelity/accuracy rather than creative range. AgentGRIT
# has no opinion on which shape is right for you, only that whatever you
# pick still answers to AGENTGRIT_CONSTITUTION above.
# -----------------------------------------------------------------------
TEMPLATE = ProjectSoul(
    project_key="your_project_key",
    display_name="Your Project Name",
    personas=(
        Persona(
            name="Persona name",
            role="What this persona is responsible for",
            voice="How it sounds -- tone, vocabulary, what it never does",
            values="The one or two things this persona will not compromise on",
            grounded_in="path/to/the/real/docs this persona's voice is built from",
        ),
    ),
    collaboration=(
        "If you have more than one persona, describe how they hand off to "
        "each other. Leave this empty for a solo persona."
    ),
)

SOULS: dict[str, ProjectSoul] = {
    # "your_project_key": TEMPLATE,   # uncomment and fill in your own
}


def render_persona_block(project_key: str | None) -> str:
    """Render the persona block for a project, or '' if none is registered."""
    if not project_key:
        return ""
    soul = SOULS.get(project_key)
    if not soul:
        return ""
    lines = [f"## Project soul: {soul.display_name}", ""]
    for p in soul.personas:
        lines.append(f"### {p.name} -- {p.role}")
        lines.append(f"Voice: {p.voice}")
        lines.append(f"Non-negotiable: {p.values}")
        lines.append("")
    if soul.collaboration:
        lines.append(f"How they work together: {soul.collaboration}")
        lines.append("")
    lines.append(f"AgentGRIT mandate underneath the persona(s): {soul.agentgrit_mandate}")
    return "\n".join(lines)
