# Discord Image Logger

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Security Policy](https://img.shields.io/badge/security-policy-red.svg)](SECURITY.md)
[![Educational / Authorized Use Only](https://img.shields.io/badge/use-educational%20%2F%20authorized%20only-lightgrey.svg)](#legal--responsible-use-disclaimer)
[![Dependencies: none](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen.svg)](requirements.txt)

An event-driven web application for **authorized, laboratory-grade demonstration** of
Discord image/attachment event handling, outbound webhook delivery, and locally
exposed HTTP endpoints reached through a development tunnel.

> [!WARNING]
> **Authorized use only.** This repository exists for education, CTF/lab exercises,
> and security research on systems you own or where every participant has given
> explicit, informed consent. It does **not** bypass Discord's permissions, terms,
> or security controls, and it must not be used for covert monitoring, data
> collection, or any activity you are not permitted to perform.
> See the [Legal / Responsible Use Disclaimer](#legal--responsible-use-disclaimer).

---

## Overview

**What the project does.** It runs a small, self-contained HTTP service that
serves a configurable image/link page, records *authorized* visit events
(IP address, coarse geographic data supplied by a public geolocation API,
user-agent family), renders a realtime operator dashboard, and optionally
delivers those events as Discord embed messages to a webhook the operator
controls.

**Why it exists.** The project is a teaching vehicle for a set of security
engineering concepts that are hard to learn abstractly:

- **Event-driven architecture** — HTTP requests become events that flow through
  background workers (geolocation, outbound webhook) without blocking responses.
- **Webhook security** — secret URLs, authentication tokens, outbound retry
  policies, and one-shot disable on revoked credentials.
- **HTTP tunneling** — how a service bound to `127.0.0.1` can be reached from a
  public URL during development, and what that implies for exposure.
- **Secret management, least privilege, data lifecycle, logging hygiene, and
  threat modeling** — all of which are documented in
  [SECURITY.md](SECURITY.md) and [docs/privacy.md](docs/privacy.md).

**How image/attachment events are handled.** When a request carries a crawler
user-agent (for example Discord's link-preview crawler), the service answers
with the configured image bytes so that a link preview can render during
development and testing. Human requests receive the interactive page. Events
derived from both paths are recorded as structured log entries.

> [VERIFY AGAINST IMPLEMENTATION] If your deployment includes an inbound
> `discord.py` bot that downloads *message attachments*, document its module
> layout, intents, and permission checks here. The current tree in this
> repository contains `main.py`, `run.py`, `setup.py`, and `start.sh` — see
> [Development](#development) — and integrates with Discord through an
> **outbound webhook URL**, not an inbound bot token.

**How an HTTP endpoint is exposed for development.** Local development usually
means the service listens on `127.0.0.1:8080`, which is unreachable from
outside the machine. A tunnel gives that loopback port a public HTTPS URL so
external clients (or a collaborator, or a webhook provider) can reach it.

**Why tunneling is useful.** It removes port forwarding, NAT traversal, and
firewall changes from the development loop, and it terminates HTTPS for you.
It does *not* grant access to anything you could not otherwise reach — tunnels
bypass no permissions and no platform controls.

**Controlled environments.** Run this only against a private test server, with
test accounts and synthetic images, in an environment you control.

---

## Features

Implemented in this repository:

| Feature | Notes |
|---|---|
| Configurable image/landing page | `config.json` → `image`, `message`, `redirect` |
| Crawler-aware preview rendering | `preview`: `image` (real bytes), `loading`, or `redirect` |
| Structured event logging | append-only JSONL archive (`logs/hits.jsonl`) |
| Geolocation enrichment | paced public-API lookups with caching and retry |
| Outbound Discord webhook delivery | retries with `429 retry_after`, one-shot disable on revocation |
| Realtime operator dashboard | SSE with automatic polling fallback |
| Access control | dashboard / API routes require `?token=` (`config.json` → `dashboard.token`) |
| Automatic tunnel launch | cloudflared, localhost.run (SSH), Pinggy, serveo, ngrok |
| Interactive setup wizard | `setup.py` validates webhook and image URLs before saving |
| Zero dependencies | Python standard library only |
| Startup self-test | confirms the tunnel really reaches the local server |

Not implemented in this repository (do not claim them in derived docs):

- inbound `discord.py` bot / attachment download → **[VERIFY AGAINST IMPLEMENTATION]**
- automatic data-retention deletion job → see [Data Retention](#data-retention)
- automated test suite → see [Testing](#testing)
- `.env` loader → configuration is `config.json` plus two environment variables,
  see [Configuration](#configuration)

---

## Architecture

```mermaid
flowchart TB
    subgraph Operators["Authorized environment"]
        VIS[Visitor / test client<br/>consented testing]
        OP[Operator dashboard<br/>token-protected]
    end

    subgraph Service["Local service 127.0.0.1"]
        HTTP[HTTP server<br/>main.py]
        PROC[Event processor]
        GEO[Geolocation worker<br/>paced + cached]
        WH[Webhook worker<br/>retry / backoff]
        LOG[("JSONL archive")]
    end

    subgraph Edge["Development tunnel"]
        TUN[Tunnel provider<br/>HTTPS edge]
    end

    subgraph External["External services"]
        GEOAPI[Geolocation API]
        DISC[Discord webhook<br/>operator-controlled]
    end

    VIS -->|HTTPS via tunnel| TUN
    TUN --> HTTP
    HTTP --> PROC
    PROC --> LOG
    PROC --> GEO
    GEO --> GEOAPI
    PROC --> WH
    WH --> DISC
    OP -->|?token=| TUN
```

**Components**

| Component | Responsibility |
|---|---|
| HTTP server | Accepts requests, routes crawler vs. human traffic, enforces token auth, never blocks on enrichment |
| Event processor | Turns a request into a structured event; discards noise such as favicon requests |
| Geolocation worker | Enriches events with coarse location from a public API, paced and cached to respect rate limits |
| Webhook worker | Queues outbound Discord embeds, honours `429 retry_after`, disables itself if the webhook is revoked |
| JSONL archive | Durable, append-only history that is replayed into the dashboard on restart |
| Tunnel | Public HTTPS front door to a loopback-only service during development |
| Dashboard | Token-gated realtime view (SSE with polling fallback) |

Full detail, including event-flow, security-boundary, and data-lifecycle
diagrams: [docs/architecture.md](docs/architecture.md).

---

## Requirements

- **Python** 3.10 or newer (developed and verified on 3.14).
- **No third-party packages** — `requirements.txt` is intentionally empty of
  runtime dependencies.
- **A Discord webhook URL** you created yourself in a server you administer.
- **Git** (only if cloning) and a POSIX shell for `start.sh`.
- **A tunnel provider** — `cloudflared` is downloaded automatically; SSH-based
  providers need an `ssh` client; ngrok is optional and needs an authtoken.
- **Environment variables** (optional overrides):

  | Variable | Purpose |
  |---|---|
  | `IMAGE_LOGGER_WEBHOOK` | Overrides `config.json` → `webhook` at runtime |
  | `NGROK_AUTHTOKEN` | Supplies the ngrok credential (or use `config.json` → `ngrokAuthtoken`) |

> Never commit a real bot token, webhook secret, or tunnel credential.

---

## Installation

```bash
git clone <repository-url>
cd IMAGE-LOGGER

python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1
# Windows (cmd)
# .venv\Scripts\activate.bat

pip install -r requirements.txt     # no runtime dependencies; confirms your venv works
```

**About dependency installation.** The runtime is standard-library only, so
`pip install -r requirements.txt` succeeds without downloading anything. The
virtual environment still matters: it isolates Python versions, keeps system
packages clean, and makes the documented commands reproducible.

Sanity check (imports configuration, starts no server):

```bash
python3 -c "import main; print('import ok')"
```

---

## Configuration

Configuration lives in **`config.json`** (created with safe defaults on first
run) and is walked through interactively by:

```bash
python3 setup.py
```

The wizard validates the webhook URL and the image URL before saving, prints a
dashboard token, and can launch the app with `--start`.

`.env.example` is provided for deployments that standardise on environment
files. **Populate it locally only — never commit a filled-in copy.**

```dotenv
DISCORD_TOKEN=
WEBHOOK_URL=
TUNNEL_URL=
LOG_LEVEL=INFO
DATA_RETENTION_DAYS=7
MAX_IMAGE_SIZE_MB=10
```

| Variable | Meaning | Honoured today? |
|---|---|---|
| `DISCORD_TOKEN` | Bot token, *if* an inbound bot module is present | [VERIFY AGAINST IMPLEMENTATION] — no bot module in this tree |
| `WEBHOOK_URL` | Destination Discord webhook | Partially — the app reads `IMAGE_LOGGER_WEBHOOK` |
| `TUNNEL_URL` | Fixed tunnel hostname to advertise | [VERIFY AGAINST IMPLEMENTATION] — URLs are discovered at launch |
| `LOG_LEVEL` | Verbosity of console logging | [VERIFY AGAINST IMPLEMENTATION] |
| `DATA_RETENTION_DAYS` | Age after which collected events are deleted | **Not enforced yet** — see [Data Retention](#data-retention) |
| `MAX_IMAGE_SIZE_MB` | Largest accepted image | **Not enforced yet** — see [Threat Model](#threat-model) |

Key `config.json` entries:

| Key | Purpose |
|---|---|
| `webhook` | Discord webhook URL (revoked sample value ships in the repo — replace it) |
| `host` / `port` | Local bind address; keep `127.0.0.1` unless you have a reason |
| `image`, `message`, `redirect` | What a visitor sees |
| `preview` | `image` \| `loading` \| `redirect` served to link-preview crawlers |
| `username` / `color` | Outbound embed display name and colour |
| `linkAlerts` | Emit an event when the link is unfurled in chat |
| `accurateLocation` | Off by default; enables a browser location prompt (**asks the visitor**) |
| `dashboard.token` | Auto-generated; required for `/dashboard`, `/events`, `/api/logs`, `/api/link` |
| `tunnel` | `auto` \| `cloudflared` \| `pinggy` \| `ssh` \| `serveo` \| `ngrok` \| `none` |
| `logFile` | JSONL archive path |

---

## Discord Configuration

1. **Create an application** — Discord Developer Portal → *New Application*.
2. **Create a webhook in a server you administer** — Server Settings →
   Integrations → Webhooks → New Webhook → *Copy Webhook URL*. Paste it into
   `config.json` → `webhook`, or export `IMAGE_LOGGER_WEBHOOK`.
3. **Configure intents/permissions** — not required for the webhook-only
   integration in this tree. If you add an inbound bot
   [VERIFY AGAINST IMPLEMENTATION], enable **only** the intents it needs
   (typically message content intent *only if* it must read attachments), and
   request the **minimum** permission set on the invite.
4. **Invite to an authorized test server** — use a private server with test
   accounts only.
5. **Least privilege** — no administrator, no manage-messages, no privileged
   permissions beyond what the code demonstrably uses.
6. **Transparency** — server members and admins must be told that image events
   are being processed, what is stored, and for how long. Post a notice in the
   test server before running anything.

---

## Tunnel Configuration

### Local Development Tunnel

A tunnel lets a locally running HTTP service receive requests from an
externally reachable URL while you develop.

Conceptually:

```text
Local application:   http://127.0.0.1:8080
Tunnel:              https://example-tunnel.example
Public client  ----> https://example-tunnel.example ----> 127.0.0.1:8080
```

Substitute **your own** tunnel URL; the example host is a placeholder.

This project launches a tunnel automatically:

```bash
python3 run.py                  # auto: cloudflared → ssh → pinggy → serveo (→ ngrok if a token is set)
python3 run.py --tunnel pinggy  # force a specific provider
python3 run.py --no-tunnel      # local only
```

All providers except ngrok require **no account**. The launcher prints the
public URL, a token-protected dashboard URL, and runs a self-test that proves
the tunnel really reaches *this* application (it validates the response body,
not just a `200`).

> Cloudflare quick tunnels (`*.trycloudflare.com`) are rate-limited per IP; a
> `429` during provisioning is a provider-side limit, not an error to work
> around by making more requests. Wait, or switch provider.

Provider-specific caveats (free Pinggy tunnels show a screening page to
browsers *and* to Discord's link-preview crawler) are documented in
[docs/tunnel.md](docs/tunnel.md).

### Tunnel Security

- **HTTPS** — only publish over TLS-terminated endpoints.
- **Authentication** — keep `dashboard.token` required; set it to `""` only on
  a trusted local network.
- **Secret validation** — reject requests that do not carry the expected token
  or shared secret.
- **Rate limiting** — the geolocation and webhook workers are already paced;
  add request-level limits before exposing anything beyond a lab.
- **IP restrictions** — restrict administrative routes where your tunnel
  provider supports it.
- **Request validation** — validate method, path, headers, and body size
  before processing.
- **No secrets in URLs** — query-string tokens end up in proxy logs; prefer
  headers when your tooling allows.
- **Rotate tunnel credentials** — regenerate dashboard tokens and webhook URLs
  when someone leaves the project.
- **Disable when idle** — stop the tunnel the moment testing finishes
  (`Ctrl+C`); an unused public URL is an unnecessary exposure.

---

## Usage

Consent applies to every step.

```bash
# 1. Configure (validates webhook + image)
python3 setup.py

# 2. Start local application + tunnel
python3 run.py
#   local     http://127.0.0.1:8080
#   public    https://<your-tunnel-host>
#   dashboard https://<your-tunnel-host>/dashboard?token=<token>
#   self-test PASSED

# 3. If you use a fixed tunnel URL, record it in config.json / .env
#    (TUNNEL_URL is [VERIFY AGAINST IMPLEMENTATION] — URLs are discovered at launch)

# 4. If your deployment includes an inbound bot: start it now
#    [VERIFY AGAINST IMPLEMENTATION]

# 5. Open the public link from a test account in your private test server
#    (or simply visit it yourself)

# 6. Watch the event appear on the dashboard, in logs/hits.jsonl,
#    and — if a valid webhook is configured — as a Discord embed
```

Stop everything with `Ctrl+C`; the tunnel is torn down with the process.

---

## Example Event

Sanitized example of an archived event:

```json
{
  "event": "image_attachment",
  "guild_id": "REDACTED",
  "channel_id": "REDACTED",
  "message_id": "REDACTED",
  "filename": "example.png",
  "content_type": "image/png",
  "size": 123456,
  "timestamp": "2026-01-01T00:00:00Z"
}
```

| Field | Meaning |
|---|---|
| `event` | Event discriminator |
| `guild_id` / `channel_id` / `message_id` | Discord identifiers, **redacted** in documentation and examples |
| `filename` | Attachment file name as provided by the client |
| `content_type` | MIME type reported for the attachment |
| `size` | Size in bytes |
| `timestamp` | ISO-8601 UTC time of the event |

> [VERIFY AGAINST IMPLEMENTATION] The exact field set written by this codebase
> differs (it records client IP, coarse geo, user-agent family, and request
> path rather than Discord IDs). Always publish examples produced from
> **synthetic** test data, never from real participants.

---

## Privacy

Images, filenames, and request metadata can all contain personal information.

- **Do not collect images or events from people who have not consented.**
- **Retain for the shortest period that meets your testing goal** — see
  [Data Retention](#data-retention).
- **Provide deletion** — delete `logFile` entries on request; document how.
- **Minimize** — avoid capturing message content you do not need; avoid
  storing Discord identifiers at all unless the exercise requires them.
- **Protect logs** — `logs/` is git-ignored; keep filesystem permissions tight
  and never sync archives to a shared drive without review.
- **Never publish collected data** — no screenshots of real events in issues,
  PRs, wikis, or social posts.
- **Never commit real images** — use synthetic test images for every example.

Full policy: [docs/privacy.md](docs/privacy.md).

---

## Data Retention

| | |
|---|---|
| **Default policy** | 7 days |
| **Recommended** | The shortest period that satisfies the exercise; shorter is better |
| **Current implementation** | Events accumulate in `logFile` (`logs/hits.jsonl`). **Automatic pruning is not implemented** — mark `DATA_RETENTION_DAYS=7` in `.env.example` as the intended policy and delete manually or via your own cron until it ships. [VERIFY AGAINST IMPLEMENTATION] |
| **Deletion mechanism** | Stop the service, remove the archive (and any dashboard state), restart. Keep a written record of what was deleted. |

Guidance: write retention as code (a scheduled job that drops entries older
than *N* days at startup and on a timer) rather than relying on someone
remembering. See [Roadmap](#roadmap).

---

## Security

Full policy in [SECURITY.md](SECURITY.md); the operational summary:

**NEVER commit:**

```text
.env                      Discord bot tokens
config.json (if filled)   webhook secrets / tunnel authtokens
*.key, *.pem              private certificates
logs/                     collected events
data/, uploads/           any collected images
secrets/, credentials/    anything else sensitive
```

Example `.gitignore` (the repository's [.gitignore](.gitignore) extends this):

```gitignore
.env
.env.*
!.env.example
__pycache__/
*.pyc
.venv/
venv/
logs/
data/
uploads/
*.log
secrets/
credentials/
.DS_Store
```

Practices: secrets in environment variables only · least-privilege bot
permissions · HTTPS everywhere · token-gated admin routes · input validation ·
request rate limits · log sanitization (never log tokens, webhook secrets, or
`Authorization` headers) · dependency updates · tunnel disabled when not in use.

---

## Threat Model

**Assets** — bot token (if present) · webhook URL · collected test data ·
tunnel credentials · dashboard token · server configuration.

| Threat | Mitigation (implemented / recommended) |
|---|---|
| Token leakage via commits | `.gitignore`, `.env.example` placeholders, secret scanning |
| Unauthorized endpoint access | `dashboard.token` → HTTP 401 on `/dashboard`, `/events`, `/api/logs`, `/api/link` |
| Malicious uploads | [VERIFY AGAINST IMPLEMENTATION] — no upload path is exercised in this tree; validate before adding one |
| Oversized files | [VERIFY AGAINST IMPLEMENTATION] — enforce `MAX_IMAGE_SIZE_MB` before accepting bodies |
| Malicious filenames | Never use client-supplied names as filesystem paths; sanitize/allow-list |
| Webhook abuse | Webhook worker disables itself on 401/403/404 responses |
| Exposed tunnel | Keep `host: 127.0.0.1`; stop the tunnel when testing ends; token-gate admin routes |
| Accidental publication of private data | Git-ignored `logs/`, sanitized examples, review before publishing |
| Geolocation API rate limiting | Paced worker, cache with TTL, fallback provider |
| Restart flood / worker starvation | Bounded queue (maxsize 500), background threads |

---

## Abuse Prevention

**This project must not be used to:**

- secretly monitor users;
- collect private images without consent;
- steal personal data or credentials;
- deploy against servers or people without permission;
- bypass Discord permissions or platform security controls;
- evade detection;
- conduct unauthorized surveillance of any kind.

**Recommended practice:**

- private test servers with test accounts only;
- synthetic images for every example and screenshot;
- explicit, documented, revocable consent from every participant;
- isolated development environments (VM/container) with no personal data;
- written scope and stop conditions before each session.

---

## Responsible Disclosure

Report security issues **privately** — do not open a public issue for
vulnerabilities, do not weaponize findings, and do not test against systems
you are not authorized to touch.

- Process, scope, and what to include: [SECURITY.md](SECURITY.md)
- Maintainer contact: **vyzx.live@gmail.com**

---

## Legal / Responsible Use Disclaimer

This repository is provided for educational, research, and authorized
security-testing purposes. Users are responsible for complying with Discord's
Terms of Service, applicable laws, privacy requirements, and the rules of any
server or system they interact with. Only collect or process content when you
have appropriate authorization and consent. The maintainers do not authorize or
encourage unauthorized monitoring, surveillance, data collection, credential
theft, privacy violations, or abuse.

A disclaimer does not make otherwise-improper use acceptable: authorization and
consent are requirements, not footnotes.

---

## Discord Terms / Platform Rules

Before deploying anything derived from this project, review the **current**
Discord Developer Terms, Developer Policy, Community Guidelines, and any
applicable data-protection rules yourself, and re-check them periodically —
they change. This documentation makes **no claim of legal compliance** and is
not legal advice.

---

## Troubleshooting

### Bot does not detect attachments

- Missing or over-broad intents → enable only what the code uses. [VERIFY AGAINST IMPLEMENTATION]
- Insufficient permissions in the test channel.
- Event handler not registered / bot not connected (check the connection log).
- Wrong channel permissions for the bot role.
- *(For this tree: there is no inbound bot — confirm you are looking at the
  webhook-outbound path instead.)*

### HTTP endpoint unavailable

- Local server not running (`python3 run.py` exits early? read its output).
- Wrong port — the launcher auto-increments if the port is busy.
- Local firewall blocking loopback or the chosen port.
- Tunnel not running or its URL changed on restart.
- Wrong URL — copy the printed `public` line exactly.

### Tunnel returns 429

Public tunnels are rate-limited by their providers.

- Check the provider's status page.
- Authenticate the tunnel where the provider requires it (e.g. ngrok authtoken).
- Avoid hammering the endpoint with automated retries.
- Use a persistent, authenticated tunnel for legitimate ongoing development.
- Read your application logs for the provider's exact message.

Do **not** attempt to circumvent provider rate limits.

### Environment variables not loading

- Confirm the file name and location (`.env` next to the entry point).
- Export values in the shell if no loader is present
  (`export IMAGE_LOGGER_WEBHOOK=...`).
- Restart the process after changing values — environment variables are read
  at start-up.

---

## Development

**Actual structure of this repository:**

```text
IMAGE-LOGGER/
├── main.py            # HTTP server, dashboard, geo + webhook workers, config
├── run.py             # launcher: server + tunnel + self-test
├── setup.py           # interactive configuration wizard
├── start.sh           # convenience wrapper
├── config.json        # local configuration (git-ignored)
├── requirements.txt   # no runtime dependencies
├── .env.example       # environment-variable template
├── .gitignore
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── LICENSE            # MIT
└── docs/
    ├── getting-started.md
    ├── configuration.md
    ├── architecture.md
    ├── tunnel.md
    ├── privacy.md
    ├── security.md
    ├── troubleshooting.md
    ├── testing.md
    └── development.md
```

If your fork contains an inbound bot module, an example layout would be:

```text
bot/client.py  bot/events.py  bot/permissions.py
server/app.py  server/routes.py
config.py  main.py
```

**[VERIFY AGAINST IMPLEMENTATION]** — that layout is illustrative only; those
files do not exist in this tree.

---

## Testing

Safe strategy — private test server, test account, synthetic images, local HTTP
server, mock events, mock webhook endpoint.

Representative cases:

| Case | Expectation |
|---|---|
| PNG attachment / image request | Valid image bytes, correct content type |
| JPG request | Valid JPEG, decodable |
| Unsupported file type | Rejected with 4xx, nothing archived |
| Oversized file | Rejected at the size limit [VERIFY AGAINST IMPLEMENTATION] |
| Missing attachment | No event recorded |
| Malformed request | 4xx, no traceback leaked |
| Invalid authentication | 401 from `/dashboard` and `/api/*` |
| Duplicate event | Idempotent or de-duplicated [VERIFY AGAINST IMPLEMENTATION] |
| Tunnel unavailable | Clear error, local mode still works |

Note: this repository currently ships **no automated test suite** — see
[docs/testing.md](docs/testing.md) for the strategy and how to contribute one.

---

## Logging

**Never log:** bot tokens · webhook secrets · `Authorization` headers ·
credential-bearing URLs · unnecessary message content · sensitive personal
information.

Sanitized examples:

```text
21:02:08 NET     self-test verified: Discord Image Logger v3.0 through the tunnel
21:03:11 WEBHOOK sent → image logger - IP Logged
21:03:41 GEO     203.0.113.10 → coarse location resolved
```

Bad:

```text
WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<secret>
Authorization: Bearer <redacted-token>
```

---

## Performance

- **Async/background event handling** — enrichment runs on worker threads so
  requests are answered immediately.
- **Request timeouts** — outbound calls are bounded; never block indefinitely.
- **Queueing** — bounded queue (500 entries) protects memory when a provider
  is slow.
- **Rate limiting** — geolocation pacing respects provider quotas.
- **File-size limits** — enforce before buffering bodies. [VERIFY AGAINST IMPLEMENTATION]
- **Memory usage** — preview image is cached once; events stream to disk.
- **Cleanup** — bound the archive size/age (see Data Retention).

---

## Limitations

- Discord permissions still apply — no code grants access you were not given.
- The system cannot reach private content it has no authorization to read.
- Tunneling does **not** bypass permissions, network policy, or platform rules.
- Network connectivity can fail; public tunnels change URLs on restart.
- Public tunnels impose quotas, screening pages, and availability limits.
- Discord APIs, crawler user-agents, and provider terms change over time.
- Privacy and security outcomes depend entirely on how you deploy and configure it.

---

## Roadmap

Safe improvements under consideration:

- configurable retention with automatic cleanup
- explicit consent capture and revocation flow
- audit logs for administrative actions
- stronger authentication (constant-time token compare, header-based secrets)
- structured logging and monitoring
- encrypted storage for collected data
- automated test suite and CI
- Docker packaging
- dashboard privacy controls and redaction toggles

Anything related to stealth, evasion, credential theft, or unauthorized
surveillance is out of scope and will not be accepted.

---

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
Security-sensitive changes must explain their threat model. Never submit real
user data, real images, or secrets.

---

## License

This project is released under the **MIT License** — see [`LICENSE`](LICENSE)
for the full text.

```text
MIT License
Copyright (c) 2026 vyntrion

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The MIT license permits use, modification, and redistribution, including for
commercial purposes, provided the copyright notice is retained. It carries
**no warranty** — see the license text. Licensing does not change the
[authorized-use expectations](#legal--responsible-use-disclaimer) documented
above: you remain responsible for complying with Discord's terms, applicable
law, and the consent of everyone involved.
