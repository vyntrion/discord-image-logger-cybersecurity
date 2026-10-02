# Getting Started

This guide takes you from a clean checkout to a running, token-protected
instance in a **private, authorized test environment**.

> **Before you begin:** you need authorization to run this — your own test
> server, test accounts, and consent from every participant. If you do not
> have that, stop here.

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Verified on 3.14 |
| Git | Only to clone |
| Discord webhook URL | Created by **you**, in a server **you** administer |
| Tunnel provider | `cloudflared` downloads automatically; SSH providers need `ssh`; ngrok is optional |
| Shell | `bash` for `start.sh` (optional) |

No third-party Python packages are required — the runtime is standard library
only.

## 2. Install

```bash
git clone <repository-url>
cd IMAGE-LOGGER

python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (cmd):         .venv\Scripts\activate.bat

pip install -r requirements.txt
```

## 3. Configure

```bash
python3 setup.py
```

The wizard:

1. Generates a **dashboard token** (keep it private).
2. Asks for your **webhook URL** and validates it with a read-only API call —
   you will see `✓ OK → #channel` or a clear error (a revoked webhook reports
   `404`).
3. Asks for the **image URL** and verifies it actually returns image bytes.
4. Asks for **bot name**, **embed colour**, **port**, and **tunnel provider**.
5. Writes `config.json`.

Non-interactive example:

```bash
python3 setup.py --yes --tunnel ssh --start
```

Prefer environment files? Copy the template and fill it in locally:

```bash
cp .env.example .env      # never commit .env
```

See [configuration.md](configuration.md) for every variable.

## 4. Start

```bash
python3 run.py
```

Expected output:

```text
  local     http://127.0.0.1:8080
  public    https://<your-tunnel-host>
  dashboard https://<your-tunnel-host>/dashboard?token=<token>
  self-test PASSED
```

The **self-test matters**: it fetches `/healthz` through the tunnel and
validates the JSON body, proving the public URL reaches *this* application and
not some provider landing page.

## 5. Exercise it (with consent)

1. Visit the printed `public` URL from a test account.
2. Open the `dashboard` URL — the event appears in realtime.
3. Check `logs/hits.jsonl` for the archived entry.
4. If a valid webhook is configured, a Discord embed arrives in your channel.

## 6. Stop

`Ctrl+C` stops the server **and** tears the tunnel down. A public URL you are
not using is an exposure — stop when testing ends.

## Consent checklist

- [ ] Private test server, test accounts only
- [ ] Every participant told what is collected and for how long
- [ ] Synthetic images used for all examples/screenshots
- [ ] Retention window decided before the first event
- [ ] No personal data in this environment

## Next steps

- [architecture.md](architecture.md) — how the pieces fit together
- [tunnel.md](tunnel.md) — tunnel providers and their caveats
- [privacy.md](privacy.md) — what is collected and why
- [troubleshooting.md](troubleshooting.md) — when something goes wrong
