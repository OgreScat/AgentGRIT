# Post-Mortem-to-Rule Discipline

AgentGRIT's Zeroth Law says an agent must not, through silence or inaction, allow a foreseeable
harm to go unreported. The corollary for the humans running GRIT is the same idea pointed inward:
when an audit, a self-grade, or a real failure surfaces a gap, the fix isn't just patching the
one instance -- it's turning the gap into a permanent rule so the same class of failure can't
recur silently.

This is a discipline, not a suggestion. Treat it as a required last step whenever you find a real
gap, not an optional nice-to-have.

## The procedure

1. **Write it up.** A short, honest incident summary: what happened, what should have happened,
   and why the existing rules didn't catch it. No blame, no minimizing -- just the mechanism of
   the failure.
2. **Encode the fix as a rule, not a one-off patch.** If the gap was a missing block, add it to
   `BLOCKED_PATTERNS` in `src/governance/bylaws.py`. If it was a missing escalation, add an
   `EscalationTrigger`. If it was a missing verification step, add it to whatever checks
   `src/execution/verification.py` runs. The point is that the *next* agent to hit this situation
   is caught by a rule, not by luck or a human happening to notice again.
3. **Cite it in the next audit.** When you (or an agent) run a self-grade or a readiness check,
   the write-up from step 1 should be checked against: did this class of gap actually get closed,
   or does it just look closed?

## Worked example: `repo_publish`

`src/governance/bylaws.py` has an `EscalationTrigger` named `repo_publish` that matches patterns
like `gh repo create ... --public` and `git remote add`. It exists because an earlier self-grade
of this exact framework found that publishing a repository publicly triggered **zero escalation**
under the rules as they were originally written -- a real, foreseeable risk (leaking secrets,
publishing something not ready, changing a repo's visibility) that the bylaws simply didn't know
to flag.

The fix wasn't "remember to be careful next time you publish a repo." The fix was: write down
what happened, add `repo_publish` as a named `EscalationTrigger`, and reference it directly in
the Zeroth Law's docstring so future readers of the bylaws understand *why* it's there. That's
the shape every post-mortem here should take.

## What doesn't count

- Fixing the immediate instance without touching the rules that let it happen. If the same
  category of gap can recur because nothing structural changed, the post-mortem isn't done.
- A verbal note or a comment with no enforcement behind it. If it's worth writing down, it's
  worth encoding as something the bylaws engine actually checks.
- Skipping this step because "it was an edge case." Edge cases are exactly what this discipline
  exists to close, one at a time, so the rule set gets more complete over time instead of staying
  static.
