# Development

## Actual repository structure

```text
IMAGE-LOGGER/
├── main.py            # HTTP server, dashboard, geo + webhook workers, config loading
├── run.py             # launcher: starts server, acquires tunnel, runs self-test
├── setup.py           # interactive configuration wizard (validates webhook/image)
├── start.sh           # convenience wrapper (runs setup on first run, then run.py)
├── config.json        # local configuration — git-ignored
├── requirements.txt   # intentionally empty of runtime dependencies
├── .env.example       # environment-variable template (placeholders only)
├── .gitignore
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── docs/              # this documentation set
├── logs/              # JSONL archive created at runtime — git-ignored
├── cloudflared        # tunnel binary, downloaded on demand — git-ignored
└── ngrok              # tunnel binary, downloaded on demand — git-ignored
```

If your fork contains an inbound bot module, an *example* layout would look
like this — **those files do not exist in this tree**:

```text
bot/client.py  bot/events.py  bot/permissions.py
server/app.py  server/routes.py
config.py  main.py
```

**[VERIFY AGAINST IMPLEMENTATION]** — confirm against your own source before
documenting it as real.

## Design principles

1. **Standard library only.** A new dependency needs a written justification
   in the PR.
2. **Never block the client.** Geolocation and webhook delivery run on
   background workers with bounded queues.
3. **Fail loudly, locally.** Provider errors (tunnel `429`, revoked webhook)
   are printed with the provider's own message rather than swallowed.
4. **Verify, don't assume.** The startup self-test validates the tunnel by
   reading the `/healthz` body — a `200` alone proves nothing when providers
   serve landing pages.
5. **Safe defaults.** Loopback bind, generated dashboard token, GPS off.

## Running locally

```bash
python3 setup.py                 # first time / reconfigure
python3 run.py --no-tunnel       # local only
python3 run.py                   # local + tunnel
python3 run.py --tunnel ssh      # specific provider
```

## Code map (`main.py`)

| Area | Responsibility |
|---|---|
| Config loading | Merges defaults + `config.json`, applies `IMAGE_LOGGER_WEBHOOK`, generates `dashboard.token` |
| HTTP handler | Routes: `/healthz`, dashboard, API, preview/image, page, favicon |
| Event logging | `_log_hit` normalizes an event and appends JSONL; replay on restart |
| Geolocation worker | Paced lookups with cache TTLs and a fallback provider |
| Webhook worker | Queue → embed build → POST with `429 retry_after` backoff → one-shot disable on `401/403/404` |
| Dashboard | HTML/JS with SSE primary and polling fallback |

| File | Responsibility |
|---|---|
| `run.py` | Arg parsing, tunnel providers (`cloudflared`, `ssh`, `pinggy`, `serveo`, `ngrok`), self-test, signal handling, restart-on-death |
| `setup.py` | Prompting, validation, writing `config.json`, prerequisite checks |

## Style

- Follow the surrounding style; keep imports stdlib-only.
- Type hints where they clarify.
- Comments explain *why*, not *what*.
- Never log secrets; never print full webhook URLs.

## Checks before you push

```bash
python3 -m py_compile main.py run.py setup.py
bash -n start.sh
git diff --cached | grep -iE "discord\.com/api/webhooks|authtoken|BEGIN .* PRIVATE KEY" || echo "clean"
```

> [VERIFY AGAINST IMPLEMENTATION] Add your formatter/linter commands here once
> adopted (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

## Extending safely

| If you want to… | Do this |
|---|---|
| Add an inbound bot | Document intents/permissions, request minimum scope, update [privacy.md](privacy.md) with every new field collected |
| Add file uploads | Enforce `MAX_IMAGE_SIZE_MB`, sanitize names, store outside the web root, define retention |
| Add new outbound calls | Add timeouts, retries with backoff, and secret-safe logging |
| Add a dashboard feature | Keep token gating; redact IPs/identifiers by default |
| Add retention | Implement `DATA_RETENTION_DAYS` pruning and document the deletion path |

Every change that touches collected data must update
[privacy.md](privacy.md) and [security.md](security.md) in the same PR.

## Performance notes

- Response path is synchronous and cheap; enrichment is asynchronous.
- Bounded queue (500) protects memory when a provider stalls.
- Preview image is fetched once and cached; archive streams to disk.
- Tunnel restarts are handled automatically and print the new URL.

## Releases

- Tag versions; update the supported-versions table in
  [SECURITY.md](../SECURITY.md).
- Changelog entries must not contain real data or secrets.
