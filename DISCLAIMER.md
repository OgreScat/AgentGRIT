# Disclaimer

AgentGRIT is a governance framework for AI agents. It is provided **as is**,
without warranty of any kind, express or implied (see LICENSE — FSL-1.1-MIT).

Plainly:

- **Governance is not a guarantee.** This framework adds review gates, capability
  fences, escalation triggers, and audit trails around AI agents. It reduces
  classes of failure; it does not eliminate them. An agent governed by this
  framework can still make mistakes, produce harmful output, or take actions you
  did not intend.
- **You are the operator.** You are responsible for what your agents do: the
  models you approve, the capabilities you grant, the tasks you assign, and the
  actions you approve at escalation gates. Configure conservatively; widen
  fences deliberately.
- **External actions are yours.** Any agent action that touches the world
  outside your machine — API calls, purchases, messages, trades, deployments —
  is your decision and your responsibility, whatever the framework's gates said
  on the way through.
- **Security requires your setup.** Read SECURITY.md before running any exposed
  surface. Defaults are hardened where possible, but deployment security is the
  deployer's job.
- **No affiliation.** This project is not affiliated with or endorsed by any AI
  model provider or third-party service it can be configured to use.

Use at your own volition and risk. The authors and contributors accept no
liability for losses or damages arising from use of this software.
