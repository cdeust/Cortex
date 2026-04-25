# Security Policy

## Reporting a Vulnerability

If you discover a security issue in this project, **do not** open a public
issue. Instead, send a private report to the maintainer.

**Disclosure channel:** open a [private security advisory on GitHub](https://github.com/cdeust/Cortex/security/advisories/new).

Include:

- Affected version (or commit SHA)
- Reproduction steps or proof of concept
- Impact assessment (what does an exploit accomplish?)
- Suggested fix, if you have one

## Response SLA

| Severity | First response | Patch / mitigation |
|---|---|---|
| Critical (RCE, data exfiltration, auth bypass) | 24 hours | 7 days |
| High | 3 days | 14 days |
| Medium / Low | 7 days | Best effort |

## Supported Versions

Only the latest minor release on `main` receives security patches.

## Disclosure Timeline

1. Reporter sends private advisory.
2. Maintainer acknowledges receipt within the first-response SLA.
3. Maintainer + reporter agree on a coordinated disclosure date (default
   30 days from the patched release).
4. Patched release ships; reporter is credited unless they prefer
   anonymity.
5. Public advisory published on the agreed date.

## Out of Scope

- Vulnerabilities in third-party dependencies that have not been patched
  upstream — please report those upstream first.
- Issues that require an attacker to already have control of the host
  process (in-process supply-chain attacks).
- Self-inflicted misconfigurations of your own MCP server registration.

## Recognition

Reporters who follow this disclosure process are credited in the release
notes for the patched version, unless they explicitly request anonymity.
