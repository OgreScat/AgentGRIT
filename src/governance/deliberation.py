"""
Multi-tier deliberation -- the chain of command made real with local models.

  JR (junior model)    drafts / assesses the action for one project
  Manager (manager model) reviews the draft against doctrine + bylaws
  GM (this function)   combines them into a verdict the Grandmaster acts on

Every tier is a local Ollama persona (a local model + a GRIT charter). This runs
on-device, free. It fails SAFE: if any tier is unreachable, the verdict is
"escalate" -- when the machine cannot deliberate, the human decides.
"""

from __future__ import annotations

import json
import os
import urllib.request


def _ollama(model: str, prompt: str, timeout: float = 30.0) -> str | None:
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "think": False,  # some local models are reasoning models; disable thinking so the
        "options": {"num_predict": 120, "temperature": 0.2},  # visible response is not empty
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["response"].strip()
    except Exception:
        return None


def deliberate(project: str, action: str, why: str) -> dict:
    """Run JR -> Manager. Returns {jr, manager, verdict}. Fails safe to escalate."""
    jr = _ollama(
        os.environ.get("GRIT_JR_MODEL", "gemma4:12b"),
        f"Project '{project}'. Proposed action: {action}. In one or two "
        f"sentences, assess whether this is safe and in scope."
    )
    if jr is None:
        return {"jr": "", "manager": "", "verdict": "escalate",
                "note": "JR unreachable -> escalate to human"}
    mgr = _ollama(
        os.environ.get("GRIT_MGR_MODEL", "gemma4:12b"),
        f"Project '{project}'. Action: {action} (reason: {why}). The junior "
        f"assessed: {jr}. Give your one-word verdict (PROCEED, REFINE, or "
        f"ESCALATE) and one sentence why."
    )
    if mgr is None:
        return {"jr": jr, "manager": "", "verdict": "escalate",
                "note": "Manager unreachable -> escalate to human"}
    up = mgr.upper()
    verdict = ("escalate" if "ESCALATE" in up else
               "refine" if "REFINE" in up else
               "proceed" if "PROCEED" in up else "escalate")
    return {"jr": jr, "manager": mgr, "verdict": verdict, "note": ""}


if __name__ == "__main__":
    import sys
    proj = sys.argv[1] if len(sys.argv) > 1 else "example-project"
    act = sys.argv[2] if len(sys.argv) > 2 else "delete the stale build artifacts"
    d = deliberate(proj, act, "irreversible removal outside the attic")
    print("JR:     ", d["jr"][:200])
    print("MANAGER:", d["manager"][:200])
    print("VERDICT:", d["verdict"].upper(), d.get("note", ""))
