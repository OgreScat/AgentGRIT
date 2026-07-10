# Release Checklist

Publishing this repository is itself an escalation event under the bylaws
(`repo_publish` EscalationTrigger — see `src/governance/bylaws.py` and
`docs/POSTMORTEM.md` for why that rule exists). Treat every public release,
including the first, as a deliberate release event: run this list top to
bottom and record the run.

## Identity and history

- [ ] `git log --all --format='%an <%ae> / %cn <%ce>'` shows only the intended
      public identity — author AND committer, every commit.
- [ ] No unintended remotes: `git remote -v`.
- [ ] `git fsck --full --unreachable` returns nothing.
- [ ] If any commit was amended since the last check:
      `git reflog expire --expire=now --all && git gc --prune=now`.

## Content sweep (working tree AND history)

- [ ] Keyword sweep over the working tree with your private banned-term list
      (project codenames, personal names, hostnames, absolute paths from your
      machine, client or business references):
      `grep -rliE '<terms>' --exclude-dir=.git .`
- [ ] Same terms against full history: `git log --all -p | grep -iE '<terms>'`.
- [ ] Sweep the classes that audits miss: example strings, demo prompts in
      `__main__` blocks, bot help text, config-file comments, and literal
      default values that mirror personal data. Sanitizing identifiers is not
      enough — sweep for the values, not just the variable names.
- [ ] No real runtime state ships: databases, logs, eval reports, memory
      files are gitignored or reset to their empty template form.
- [ ] `.env` absent; `.env.example` contains only placeholders and neutral
      defaults.

## Mechanics

- [ ] Fresh-clone smoke test in a temp directory: create venv,
      `pip install -e ".[dev]"`, run the full test suite, run the quickstart
      commands from the README exactly as written. Note that empty
      directories do not survive `git clone` — anything the code writes to
      must be created by the code, not assumed.
- [ ] CI workflow present and green on the release commit.
- [ ] LICENSE present; copyright holder and year correct; license choice
      re-confirmed against your commercial strategy (FSL-1.1-MIT: open and
      auditable, blocks competing commercial hosting, converts to MIT after
      two years per version).
- [ ] `pyproject.toml` metadata (name, version, authors, classifiers)
      matches what you want strangers to see.
- [ ] Every document referenced from README/CLAUDE.md exists and matches
      current behavior.

## After the checks

- [ ] Record the checklist run (date, commit hash, who ran it) in your
      private notes or postmortem log.
- [ ] Push, verify CI, tag the release.
- [ ] Anything found during the run that the checklist did not cover becomes
      a new checklist line — postmortem-to-rule applies here too.
