# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `main` (unreleased) | ✅ security fixes land here first |
| v3.x | ✅ current documented line |
| < v3 | ❌ unsupported — upgrade |

Adjust this table once you cut formal releases.

## Reporting a Vulnerability

Report security issues **privately**. Do not open a public GitHub issue for
vulnerabilities, and do not publish proof-of-concept material before a fix is
available.

1. Email **`vyzx.live@gmail.com`**
   > Maintainer contact for security reports.
2. Or, if your host supports it, use the repository's *Security* → *Report a
   vulnerability* private advisory channel.
3. Allow reasonable time for a fix before any public discussion.

### What to include

- Description of the issue and its impact
- Affected version / commit hash
- Minimal reproduction steps (see *Sensitive Information* below)
- Any suggested remediation

### What **not** to include

Never send real secrets or personal data:

- Discord bot tokens
- Real user images or screenshots containing personal data
- Passwords, API keys, or webhook secrets
- Private personal data about any individual
- Live credentials for third-party services

Use synthetic, clearly fake values in every report.

### Expected response

| Stage | Expectation |
|---|---|
| Acknowledgement | Within 5 business days |
| Initial triage | Within 10 business days |
| Fix / mitigation | Proportionate to severity; critical issues prioritized |
| Credit | Reporter credited in the advisory unless they decline |

These are commitments, not guarantees — if you receive no reply within the
window, re-report through the same channel and say it is a follow-up.

### Responsible disclosure expectations

- Give maintainers a reasonable window to fix before public disclosure.
- Do not access other users' data, do not retain data beyond what proves the
  issue, and delete any data collected during testing.
- Test only against systems you own or are explicitly authorized to test.
- Do not use findings for extortion, surveillance, or any unauthorized purpose.

## Scope

In scope:

- Authentication and access-control flaws (dashboard/API token handling)
- Secret exposure in code, logs, documentation, or error messages
- Unauthorized access to the HTTP endpoint or administrative routes
- Data leakage (collected events, archives, error pages)
- Request validation issues (malformed bodies, oversized payloads, unsafe
  file-name handling)
- Dependency vulnerabilities affecting this repository

Out of scope:

- Issues in third-party tunnel providers or Discord itself
- Reports that require unauthorized access to demonstrate
- Social engineering, physical attacks, or denial-of-service against
  infrastructure you do not own
- Findings that rely on the operator deliberately disabling documented
  controls (for example setting `dashboard.token` to `""` on a public tunnel)

## Sensitive Information Handling

Maintainers will handle reported data carefully, restrict access to what is
needed to reproduce, and delete reproduction artifacts once a fix ships.
Reporters should do the same on their side.
