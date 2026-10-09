# Troubleshooting

## Events not appearing

- **Webhook revoked** — the console logs `webhook rejected with HTTP 404`.
  Create a new webhook in *your* server and re-run `python3 setup.py`.
- **Webhook not configured** — the banner prints `webhook NOT configured`;
  set `config.json` → `webhook` or `IMAGE_LOGGER_WEBHOOK`.
- **Nobody opened the link** — a "link shared" card only means the preview was
  unfurled. A visitor event appears when a human actually opens the URL.
- **Looking at the wrong channel** — webhooks post to the channel they were
  created in.
- **Dashboard auth** — `/api/logs` returns **401** without `?token=…`.
- **Event suppressed** — check `suppressed` on the event; a suppressed event
  is deliberately not delivered.

## HTTP endpoint unavailable

| Symptom | Likely cause | Fix |
|---|---|---|
| Connection refused locally | Server not running / crashed | Run `python3 run.py` and read its output |
| Wrong port | Port already in use | The launcher auto-increments; use the printed `local` URL |
| Works locally, fails publicly | Tunnel down or wrong URL | Re-copy the printed `public` line; restart |
| Blocked | Local firewall | Allow loopback on the chosen port |
| Self-test `FAILED` | URL is not reaching this app | Verify `host`/`port`, retry |

## Public URL won't open (but `run.py` printed one)

Nearly always **fresh-name DNS lag**, not a dead tunnel:

| Symptom | What it means | Fix |
|---|---|---|
| Browser says the site can't be reached / `NXDOMAIN` right after launch | The new `*.trycloudflare.com` name needs 30–90 s to enter DNS | Wait ~30 s, retry; the local URL works immediately |
| `self-test FAILED` with `Name or service not known` or an SSL error | Same lag — the launcher only reports the last error it saw | Retry until the 120 s window passes; relaunch if needed |
| `self-test PASSED` but an **old** link is dead | Quick-tunnel URLs change on every restart | Use the URL from the latest banner or `logs/tunnel.url` |
| `429` / "too many requests" | Cloudflare is rate-limiting this IP | Wait a few minutes, or `python3 run.py --tunnel ssh` |

Confirm the tunnel itself in one command (should print your `/healthz` JSON):

```bash
curl "$(cat logs/tunnel.url)/healthz"
```

## Tunnel returns 429

Public tunnels are rate-limited by their providers.

```text
quick tunnel provisioning failed with status 429
```

- Check the provider's status page.
- Authenticate the tunnel where required (e.g. ngrok authtoken).
- Avoid hammering the endpoint with automated retries.
- Use a persistent, authenticated tunnel for legitimate ongoing development.
- Read your application logs for the provider's exact message.

Do **not** attempt to circumvent provider rate limits.

## Environment variables not loading

- `.env` must sit next to `main.py`, be named exactly `.env` (not
  `.env.example`), and use `KEY=VALUE` lines — `#` comments are skipped.
- A value exported in the shell always beats the file:

  ```bash
  export IMAGE_LOGGER_WEBHOOK="https://discord.com/api/webhooks/<id>/<secret>"
  python3 run.py
  ```

- **Restart the process** — configuration is read once at start-up.
- Confirm precedence: shell > `.env` > `config.json` > built-in default.

## No image preview in the crawler

- Set `config.json` → `preview` to `image` (the crawler then receives the real
  image bytes).
- Confirm `image` points at a direct, non-hotlink-protected image URL
  (`setup.py` validates this).
- Some providers screen browser-like clients — see
  [tunnel.md](tunnel.md) → *Pinggy screening page*. Use `cloudflared` or `ssh`
  when previews must render.

## Geolocation stuck at `…`

- The client is on a LAN/private address (no public data).
- The geolocation API is rate-limited — the worker backs off and retries.
- Enrichment is asynchronous; refresh after a few seconds.

## Dashboard shows "Waiting for visitors…"

Open the printed **public** URL in a normal browser tab; local-only visits on
another device will never arrive.

## Getting more detail

Run with debug output (`LOG_LEVEL=DEBUG` in `.env`, or `config.json` →
`logLevel: "DEBUG"`) and read `logs/`. Never paste console output containing
webhook URLs or tokens into a public issue — redact them first.
