# Security Policy

Beekeeper executes tools on behalf of agents and mediates them through a policy
layer. Security issues are taken seriously.

## Supported Versions

Beekeeper is pre-1.0. Only the latest commit on `main` is supported. Pin to a
commit SHA or release tag in production and update frequently.

| Version    | Supported          |
|------------|--------------------|
| `main`     | :white_check_mark: |
| < latest   | :x:                |

## Reporting a Vulnerability

**Do not file security issues as public GitHub issues.** Public issues from
non-allowlisted contributors are auto-closed by the contribution gate, but
even an open issue is the wrong channel for a vulnerability report.

Use one of the private channels:

1. **Preferred — GitHub Security Advisories** (private):
   <https://github.com/Anmolnoor/beekeeper/security/advisories/new>
2. **Email**: security@anmolnoor.com — please include `[beekeeper-security]`
   in the subject line.

Please include:

- A clear description of the issue and the impact you believe it has.
- Reproduction steps, with code or commands where possible.
- The commit SHA you reproduced against.
- Whether the issue affects the legacy worker dispatch path, the
  model-driven tool loop, the MCP adapter, or another component.

You should expect:

- Acknowledgement within **7 days**.
- A status update within **14 days** of acknowledgement.
- Coordination with you on a fix and disclosure timeline before any public
  write-up.

## Out of Scope

The following are not security issues for the purpose of this policy:

- Findings against third-party services Beekeeper integrates with (Postgres,
  Redis, Temporal, Qdrant, SearXNG, Ollama, etc.) — report those upstream.
- Issues in user-deployed configurations or self-written workers/blueprints.
- Findings that require physical access or already-compromised credentials.

## Public Discussions

Please do not publicly discuss a potential security vulnerability before a fix
is available. Coordinated disclosure protects users.

Thank you for helping keep Beekeeper safe.
