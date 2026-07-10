# Security

AgentGRIT is a framework for governing autonomous agents. Running it exposes
capabilities (agent spawning, command execution, model routing) that must be
secured before any network exposure. This document records the standing
hardening requirements and the findings from the pre-publication sweep.

## Reporting a vulnerability

Open a private security advisory on the repository rather than a public issue.
Do not include working exploits in public issues.

## Hardening requirements before you expose the API

The FastAPI server (`src/api/server.py`) ships with sane local defaults but is
NOT hardened for network exposure out of the box. Before binding it to any
non-loopback interface:

1. **Authentication is enforced (fail closed).** A `require_api_key` dependency
   guards every endpoint except `/health` and the docs. If `API_SECRET_KEY` is
   set, requests must carry a matching `X-API-Key` header (constant-time compared).
   If no key is set, the server serves only on a loopback host — binding to a
   non-loopback interface without a key is refused with HTTP 503. You may still
   front it with a reverse proxy for TLS and rate limiting.
2. **Bind to loopback by default.** `api_host` now defaults to `127.0.0.1`.
   Only set `0.0.0.0` when the service is behind authentication and a firewall.
3. **Set a real `API_SECRET_KEY`.** The placeholder default
   (`change-me-in-production`) must be replaced with
   `openssl rand -hex 32` output. Never commit the real value.
4. **Keep `.env` out of git.** It is gitignored; verify before every push.
5. **Ollama bind.** `OLLAMA_HOST=0.0.0.0` in `docker-compose.yml` is for
   container networking; do not publish that port to the host without a reason.

## What the pre-publication sweep confirmed as sound

- Command execution in the agent path forbids `shell=True` and gates commands
  through the escalation system. The one `shell=True` (in
  `execution/verification.py`) is the internal verification harness running its
  own trusted commands with a timeout, not user input.
- Escalation tokens use `secrets.token_urlsafe`, not the `random` module.
- The Docker image creates and runs as a non-root `agentgrit` user.
- Destructive shell patterns (`rm -rf /`, `rm -rf ~`) are blocked by Law 0 in
  the bylaw engine.

## Threat model note

The bylaw engine is a self-governance layer, not a sandbox. It constrains what
a cooperating agent will choose to do; it is not a security boundary against a
compromised model or a malicious operator. Run agents with OS-level least
privilege (the Docker non-root user, restricted mounts) as the actual boundary.
