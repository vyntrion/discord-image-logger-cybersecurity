# Security

Operational security guidance for running this project. The formal policy and
reporting process live in [SECURITY.md](../SECURITY.md).

## Secret management

| Secret | Store in | Never in |
|---|---|---|
| Discord webhook URL | `config.json` (git-ignored) or `IMAGE_LOGGER_WEBHOOK` | docs, issues, screenshots, commits |
| Dashboard token | `config.json` → `dashboard.token` | public URLs, screenshots |
| ngrok authtoken | `NGROK_AUTHTOKEN` env var or `config.json` | commits, shell history in shared sessions |
| Bot token (if applicable) | environment only | anywhere, ever, in plaintext |

Rotate any secret that has been exposed: create a new webhook, regenerate the
dashboard token, re-issue the tunnel authtoken.

## Environment variables and `.gitignore`

```bash
cp .env.example .env     # populate locally
```

```gitignore
.env
.env.*
!.env.example
secrets/
credentials/
config.json
logs/
data/
uploads/
*.log
__pycache__/
*.pyc
.venv/
venv/
.DS_Store
```

`.env.example` must stay tracked (placeholders only); everything else above
must stay out of the repository.

**Never commit:**

```text
.env                        Discord bot tokens
config.json (filled)        webhook secrets, tunnel authtokens
*.key / *.pem               private certificates
logs/                       collected events
data/ , uploads/            collected images
secrets/ , credentials/     anything else sensitive
```

## Least privilege

- Run the service as an unprivileged user; no root, no sudo.
- `host` stays `127.0.0.1` — the tunnel is the only ingress.
- If an inbound bot is used **[VERIFY AGAINST IMPLEMENTATION]**: minimum
  permissions, minimum intents, private test server only.
- Filesystem: the process needs write access to `logs/` and nothing more.

## HTTPS

All supported providers terminate TLS on the public side. Do not publish an
origin over plain HTTP, and do not disable certificate verification in clients
or tests.

## Authentication

- `/dashboard`, `/events`, `/api/logs`, `/api/link` require `?token=…`.
- Missing/wrong token → **401** (verified by the project's own checks).
- Keep the token non-empty whenever the service is reachable beyond loopback.
- [VERIFY AGAINST IMPLEMENTATION] Move to header-based, constant-time
  comparison when your tooling supports it; query tokens reach proxy logs.

## Input validation

- Validate method, path, and headers before dispatching.
- Reject oversized bodies before buffering them (`MAX_IMAGE_SIZE_MB` is
  documented but **not yet enforced**).
- Never use client-supplied file names as filesystem paths — sanitize or
  allow-list them.
- Treat every header (`Cf-Connecting-Ip`, `X-Forwarded-For`, `User-Agent`) as
  attacker-controlled; they are classification hints, not identity.

## Rate limiting

Already paced: geolocation lookups (provider quota + cache) and outbound
webhook delivery (`429 retry_after` handling, bounded queue of 500).
[VERIFY AGAINST IMPLEMENTATION] Add per-IP request limits before exposing the
service beyond a small lab.

## Logging hygiene

**Never log:** tokens · webhook secrets · `Authorization` headers ·
credential-bearing URLs · unnecessary message content · personal data beyond
what the exercise needs.

```text
# good
21:02:08 NET     self-test verified: Discord Image Logger v3.0 through the tunnel
21:03:41 GEO     203.0.113.10 → coarse location resolved

# bad
WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<secret>
Authorization: Bearer <redacted-token>
```

Console output may be shared when debugging — make sure it is safe to share
*before* you paste it.

## Dependency updates

The runtime is standard-library only, which minimizes supply-chain surface.
If you add dependencies:

- pin versions;
- review releases before upgrading;
- re-run your test matrix;
- record the change in the PR (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

Keep Python itself current for security patches.

## Secure tunnel configuration

See [tunnel.md](tunnel.md) → *Tunnel Security* for the full list: HTTPS,
authentication, secret validation, rate limiting, IP restrictions, request
validation, no secrets in URLs, credential rotation, and disabling the tunnel
when testing ends.

## Hardening checklist

- [ ] `host` is `127.0.0.1`
- [ ] `dashboard.token` is non-empty and never screenshot
- [ ] `config.json` and `.env` are git-ignored
- [ ] Webhook URL is yours and works (run `setup.py` to validate)
- [ ] `accurateLocation` off unless consented
- [ ] Retention window written down; deletion tested
- [ ] Tunnel stopped when testing ends
- [ ] No secrets in git history (`git log -p | grep -i webhook` as a smoke test)
