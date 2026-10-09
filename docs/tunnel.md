# Tunnel Configuration

## What a tunnel is

A tunnel gives a service bound to `127.0.0.1` a public HTTPS URL so that
requests from outside your machine can reach it during development — without
port forwarding, NAT traversal, or firewall changes.

```text
Local application:   http://127.0.0.1:8080
Tunnel:              https://example-tunnel.example      ← placeholder, use your own
Public client  ----> https://example-tunnel.example  --> 127.0.0.1:8080
```

Tunnels are a **development convenience**. They bypass no permissions, no
platform controls, and no network policy — they only move the front door of a
service you already run.

## Providers supported by `run.py`

Everything except ngrok requires **no account**.

| Provider | Login | Launch | URL shape | Notes |
|---|---|---|---|---|
| `cloudflared` | none | auto-downloaded | `https://xxxx.trycloudflare.com` | No interstitial; link previews render. Quick tunnels are rate-limited per IP (`429`) |
| `ssh` (localhost.run) | none | needs `ssh` | `https://xxxx.lhr.life` | No interstitial observed in testing |
| `pinggy` | none | needs `ssh` | `https://xxxx.run.pinggy-free.link` | ⚠️ Free tier shows a **screening page** to browsers *and* to link-preview crawlers; tunnel expires after ~60 min (auto-renewed) |
| `serveo` | none | needs `ssh` | `https://xxxx.serveousercontent.com` | Passed content through in testing; may show a warning page in some browsers |
| `ngrok` | authtoken | auto-downloaded | `https://xxxx.ngrok-free.app` | Skipped automatically when no token is configured |
| `none` | — | — | local only | `--no-tunnel` |

## Usage

```bash
python3 run.py                  # auto: cloudflared → ssh → pinggy → serveo (→ ngrok if tokenled)
python3 run.py --tunnel pinggy   # force one provider
python3 run.py --no-tunnel       # local only
```

`config.json` → `tunnel` records your default provider.

### The self-test

After acquiring a URL, the launcher requests `/healthz` **through the tunnel**
and validates the JSON body (not just a `200`). Some providers answer unknown
paths with their own landing page, which would otherwise look like success:

```text
20:46:02 NET     self-test verified: Discord Image Logger 3.0 through the tunnel (63s)
  self-test PASSED — public link reaches this server, it is live
```

The elapsed time matters: brand-new quick-tunnel hostnames often need
60–90 s before DNS answers, so the launcher retries for **120 s** before
giving up. A failure prints the *last error it saw* (`Name or service not
known`, an SSL handshake error, a wrong body) so you can tell lagging DNS
apart from a real misconfiguration — if the error is DNS/SSL, wait ~30 s and
open the link again.

The current URL is also written to **`logs/tunnel.url`** while the tunnel is
up (and removed on shutdown), so it is never lost to terminal scrollback.

### Automatic restart

If the tunnel process dies (network blip, Pinggy's 60-minute limit), `run.py`
restarts it and prints the new URL — `logs/tunnel.url` is updated to match.
**Public URLs change on restart**; tell collaborators to re-copy rather than
bookmarking.

## Tunnel Security

1. **HTTPS** — publish only over TLS-terminated endpoints (all providers above
   do this).
2. **Authentication** — keep `dashboard.token` required on `/dashboard`,
   `/events`, `/api/logs`, `/api/link`. Setting it to `""` on a public URL
   exposes collected data to anyone.
3. **Secret validation** — reject requests missing the expected token or
   shared secret before doing any work.
4. **Rate limiting** — add request-level limits before exposing anything
   beyond a small lab; the geolocation and webhook workers are already paced.
5. **IP restrictions** — where your provider supports them, restrict
   administrative routes.
6. **Request validation** — check method, path, header presence, and body size
   before processing.
7. **No secrets in URLs** — query-string tokens land in proxy and browser
   logs. Prefer headers where your tooling allows, and never print the full
   tokenized dashboard URL in public screenshots.
8. **Rotate tunnel credentials** — regenerate dashboard tokens and webhook
   URLs when a collaborator leaves.
9. **Disable when not needed** — `Ctrl+C` when testing ends; an idle public
   URL is pure exposure.

## Common provider issues

### `429` from cloudflared

```text
quick tunnel provisioning failed with status 429
```

The provider limits how many quick tunnels one IP may create — typically after
heavy restarting. **Wait for the limit to clear**, check the provider's status
page, or switch provider. Do not try to circumvent the limit.

### Pinggy screening page

Free Pinggy tunnels serve a confirmation page to browser-like clients —
including link-preview crawlers — before content reaches the visitor. It is
shown once per browser; a crawler will not click through, so link previews may
show Pinggy's page instead of your image. Use `cloudflared` or `ssh` when the
preview must render.

### ngrok `ERR_NGROK_4018`

```text
ngrok requires an account and a valid credential to start a session
```

Create a free account, copy the authtoken, then:

```bash
python3 setup.py --ngrok-token <your-token> --yes
# or: export NGROK_AUTHTOKEN=<your-token>
```

### DNS lag on fresh URLs

New `*.trycloudflare.com` names can take **30–90 s** to resolve, and
Cloudflare itself prints "it may take some time to be reachable". Symptoms:

- the browser shows `DNS_PROBE_FINISHED_NXDOMAIN` / connection errors for the
  first minute, while `http://127.0.0.1:<port>` works instantly;
- the self-test initially fails with `Name or service not known`.

The launcher retries the self-test for **120 s** (longer than the observed
lag) and tells you the last error it saw. If it still reports `FAILED` with a
DNS/SSL error, wait ~30 s and reopen the link; if it persists, `Ctrl+C` and
relaunch for a fresh URL. The live URL is always in `logs/tunnel.url`.

## What tunnels are not

- Not a way to bypass authentication, permissions, or platform rules
- Not anonymity: the provider sees your traffic and your IP
- Not a substitute for HTTPS on the origin
- Not permanent: free URLs change and quotas apply
