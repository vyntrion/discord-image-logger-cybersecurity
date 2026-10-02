# Troubleshooting

## Bot does not detect attachments

> [VERIFY AGAINST IMPLEMENTATION] This section applies to deployments that
> include an inbound Discord bot. The tree documented in the README integrates
> with Discord through an **outbound webhook URL** and has no inbound bot — if
> you are running that configuration, see *Events not appearing* below instead.

Possible causes:

| Cause | What to check |
|---|---|
| Missing intents | Enable only the intents the code uses; privileged intents (message content, presence, members) require developer-portal opt-in |
| Insufficient permissions | The bot needs read access to the channel where the test image is posted |
| Event handler not registered | Confirm the handler is bound before `login()` |
| Bot not connected | Look for the ready/disconnect log lines |
| Wrong channel permissions | Category overwrites can silently deny the channel |
| Testing in the wrong server | Invites are guild-scoped |

**Least privilege:** request the minimum permissions and intents; do not grant
administrator.

## Events not appearing (webhook-based configuration)

- **Webhook revoked** — the console logs `webhook rejected with HTTP 404`.
  Create a new webhook in *your* server and re-run `python3 setup.py`.
- **Nobody opened the link** — a "link shared" card only means the preview was
  unfurled. A visitor event appears when a human actually opens the URL.
- **Looking at the wrong channel** — webhooks post to the channel they were
  created in.
- **Dashboard auth** — `/api/logs` returns **401** without `?token=…`.

## HTTP endpoint unavailable

| Symptom | Likely cause | Fix |
|---|---|---|
| Connection refused locally | Server not running / crashed | Run `python3 run.py` and read its output |
| Wrong port | Port already in use | The launcher auto-increments; use the printed `local` URL |
| Works locally, fails publicly | Tunnel down or wrong URL | Re-copy the printed `public` line; restart |
| Blocked | Local firewall | Allow loopback on the chosen port |
| Self-test `FAILED` | URL is not reaching this app | Verify `host`/`port`, retry |

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

- Confirm the file name/location (`.env` next to the entry point) and that it
  is not named `.env.example`.
- If no loader is present, export in the shell:

  ```bash
  export IMAGE_LOGGER_WEBHOOK="https://discord.com/api/webhooks/<id>/<secret>"
  python3 run.py
  ```

- **Restart the process** — environment variables are read at start-up.
- Confirm precedence: `IMAGE_LOGGER_WEBHOOK` overrides `config.json`.

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

Run with debug output enabled (`config.json` → `debug: true`
**[VERIFY AGAINST IMPLEMENTATION]** — confirm the key in your version) and read
`logs/`. Never paste console output containing webhook URLs or tokens into a
public issue — redact them first.
