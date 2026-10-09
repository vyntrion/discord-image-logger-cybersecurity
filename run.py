#!/usr/bin/env python3
"""
One-command launcher: local server + public tunnel.

    python3 run.py                 # cloudflared quick tunnel (no account needed)
    python3 run.py --port 3000     # pick the local port
    python3 run.py --no-tunnel     # local only
    python3 run.py --tunnel ngrok  # use ngrok if it is installed

It prints:
    * the public link you share
    * the realtime dashboard link
    * a self-test proving the tunnel really reaches the server
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import main as app  # noqa: E402

CLOUDFLARED_URL = {
    "x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "aarch64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "armv7l": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
    "armv6l": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
}


def banner(text: str) -> None:
    print("\n\033[96m" + "─" * 62 + "\033[0m")
    print(f"\033[1;96m{text}\033[0m")
    print("\033[96m" + "─" * 62 + "\033[0m")


def remember_tunnel_url(url: str) -> None:
    """Persist the live public URL to logs/tunnel.url.

    Quick-tunnel URLs change on every restart and vanish into terminal
    scrollback, which makes a working tunnel look like a dead one when an
    old link is re-opened. Keeping the current URL on disk gives the
    operator (and any test script) one authoritative place to read it.
    """
    try:
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        with open(os.path.join(ROOT, "logs", "tunnel.url"), "w",
                  encoding="utf-8") as fh:
            fh.write(url + "\n")
    except OSError:
        pass


def find_cloudflared() -> str | None:
    local = os.path.join(ROOT, "cloudflared")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    found = shutil.which("cloudflared")
    if found:
        return found

    import platform
    url = CLOUDFLARED_URL.get(platform.machine())
    if not url:
        return None
    app.say("net", "downloading cloudflared (one time)…")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=180) as resp, open(local, "wb") as out:
            shutil.copyfileobj(resp, out)
        os.chmod(local, 0o755)
        return local
    except Exception as exc:  # noqa: BLE001
        app.say("error", f"could not download cloudflared: {exc}")
        return None


def start_cloudflared(port: int) -> tuple[subprocess.Popen | None, str | None]:
    binary = find_cloudflared()
    if not binary:
        app.say("error", "cloudflared not found — install it or pass --no-tunnel")
        return None, None

    last_error: list[str] = []

    for attempt in range(2):
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://127.0.0.1:{port}",
             "--metrics", "localhost:0", "--no-autoupdate"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=ROOT,
        )
        tunnel_url: list[str] = []

        def reader(proc=proc, tunnel_url=tunnel_url) -> None:
            pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
            assert proc.stderr is not None
            for line in proc.stderr:
                match = pattern.search(line)
                if match and not tunnel_url:
                    tunnel_url.append(match.group(0))
                clean = re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip()
                if clean:
                    last_error.append(clean)
                    del last_error[:-40]          # keep the last 40 lines
                if str(app.config.get("logLevel") or "INFO").upper() == "DEBUG":
                    print("  [cloudflared]", clean)

        threading.Thread(target=reader, daemon=True).start()

        # the URL normally lands in ~5-10s, but cloudflared prints its own
        # warning that provisioning can stall — wait up to 60s before giving up
        for tick in range(120):
            if tunnel_url:
                return proc, tunnel_url[0]
            if proc.poll() is not None:
                break
            if tick == 40:
                app.say("net", "cloudflared is still provisioning a URL… "
                               "(rare stalls can take close to a minute)")
            time.sleep(0.5)

        if tunnel_url:
            return proc, tunnel_url[0]

        # timed out (or it died) -> show why, then retry once
        code = proc.poll()
        if code is None:
            app.say("error", "cloudflared produced no URL within 60s — output:")
        else:
            app.say("error", f"cloudflared exited early (code {code}) — output:")
        for line in last_error[-12:]:
            print("    " + line)
        if any(re.search(r"\b429\b|too many request", l, re.I) for l in last_error):
            app.say("warn", "cloudflare is rate-limiting this IP — wait a few "
                            "minutes before retrying, or use `--tunnel ssh` "
                            "(no login, no rate limit)")
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        if attempt == 0:
            time.sleep(2)
            last_error.clear()

    return None, None


def find_ngrok() -> str | None:
    local = os.path.join(ROOT, "ngrok")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    found = shutil.which("ngrok")
    if found:
        return found

    import platform
    arch = platform.machine()
    suffix = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm",
              "armv6l": "arm"}.get(arch)
    if not suffix:
        return None
    url = f"https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-linux-{suffix}.tgz"
    app.say("net", "downloading ngrok (one time)…")
    try:
        import tarfile
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            blob = resp.read()
        tarball = os.path.join(ROOT, ".ngrok.tgz")
        with open(tarball, "wb") as fh:
            fh.write(blob)
        with tarfile.open(tarball) as tar:
            member = next((m for m in tar.getmembers() if m.name.endswith("ngrok")), None)
            if member:
                tar.extract(member, ROOT)
                os.rename(os.path.join(ROOT, member.name), local)
        os.remove(tarball)
        os.chmod(local, 0o755)
        return local if os.path.isfile(local) else None
    except Exception as exc:  # noqa: BLE001
        app.say("error", f"could not download ngrok: {exc}")
        return None


def start_ngrok(port: int) -> tuple[subprocess.Popen | None, str | None]:
    binary = find_ngrok()
    if not binary:
        app.say("error", "ngrok is unavailable (download failed / not on PATH)")
        return None, None

    args = [binary, "http", str(port), "--log=stdout"]
    token = (app.config.get("ngrokAuthtoken") or os.environ.get("NGROK_AUTHTOKEN") or "")
    if token:
        args = [binary, "http", str(port), "--authtoken", token]

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, cwd=ROOT)
    tunnel_url: list[str] = []
    errors: list[str] = []
    pattern = re.compile(r"https://[a-z0-9-]+\.ngrok(-free)?\.(app|io|dev)")

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = pattern.search(line)
            if match and not tunnel_url:
                tunnel_url.append(match.group(0))
            if "ERR" in line or "error" in line.lower():
                errors.append(line.rstrip())

    threading.Thread(target=reader, daemon=True).start()
    for _ in range(60):
        if tunnel_url:
            return proc, tunnel_url[0]
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if not tunnel_url:
        app.say("error", "ngrok failed to give a URL — is your authtoken set? "
                         "(ngrokAuthtoken in config.json / NGROK_AUTHTOKEN env)")
        for line in errors[-5:]:
            print("    " + line)
    return proc, (tunnel_url[0] if tunnel_url else None)


SSH_HOSTS = ("nokey@localhost.run", "nokey@lhr.life", "nokey@ooguy.com")


def start_ssh(port: int) -> tuple[subprocess.Popen | None, str | None]:
    """Free reverse tunnel over SSH (localhost.run) — no account, no download."""
    if not shutil.which("ssh"):
        app.say("error", "ssh client not found — install openssh-client")
        return None, None

    last_error = ""
    for host in SSH_HOSTS:
        proc = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes",
             "-R", f"80:127.0.0.1:{port}", host],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=ROOT,
        )
        tunnel_url: list[str] = []
        pattern = re.compile(r"https://[a-z0-9-]+\.(lhr\.life|localhost\.run|ooguy\.com)")

        def reader(proc=proc, tunnel_url=tunnel_url) -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                # localhost.run's welcome banner also mentions
                # https://admin.localhost.run/ — only trust the line that
                # actually announces OUR forwarding URL.
                if "tunneled" not in line and "Forwarding" not in line:
                    continue
                match = pattern.search(line)
                if match and not tunnel_url:
                    tunnel_url.append(match.group(0).rstrip("/,."))

        threading.Thread(target=reader, daemon=True).start()
        for _ in range(40):
            if tunnel_url:
                return proc, tunnel_url[0]
            if proc.poll() is not None:
                last_error = f"{host} exited with code {proc.returncode}"
                break
            time.sleep(0.5)
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    app.say("error", f"ssh tunnel failed ({last_error or 'no URL'})")
    return None, None


# Pinggy's free tier asks for a password (any/empty) before opening the tunnel.
# SSH reads passphrases from the terminal, so we feed it an askpass helper that
# answers with an empty line — no account, no key, nothing for the user to type.
ASKPASS = os.path.join(ROOT, ".askpass.sh")
_PINGGY_HOSTS = ("pinggy-free.link", "pinggy.net", "pinggy.io", "pinggy.dev", "pinggy.link")
_PINGGY_SKIP_HOSTS = ("pinggy.io", "www.pinggy.io", "dashboard.pinggy.io")


def start_pinggy(port: int) -> tuple[subprocess.Popen | None, str | None]:
    """Pinggy — free, no signup, no download (plain SSH on port 443).

        ssh -p 443 -R0:127.0.0.1:PORT free.pinggy.io

    Yields e.g. https://navix-103-50-150-72.run.pinggy-free.link
    The free tunnel expires after ~60 min; run.py relaunches it automatically.
    """
    if not shutil.which("ssh"):
        app.say("error", "ssh client not found — install openssh-client")
        return None, None
    try:
        with open(ASKPASS, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n: \n")      # print an empty password
        os.chmod(ASKPASS, 0o700)
    except OSError:
        pass

    env = dict(os.environ)
    env.update({"SSH_ASKPASS": ASKPASS, "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": env.get("DISPLAY") or ":0"})

    proc = subprocess.Popen(
        ["ssh", "-p", "443", "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", "-o", "ServerAliveInterval=30",
         "-o", "ExitOnForwardFailure=yes",
         "-R", f"0:127.0.0.1:{port}", "free.pinggy.io"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=ROOT, env=env,
    )
    tunnel_url: list[str] = []

    def reader(proc=proc, tunnel_url=tunnel_url) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            match = re.match(r"^https://([a-z0-9.-]+)", clean, re.I)
            if not match or tunnel_url:
                continue
            host = match.group(1).rstrip("/,.")
            if not host.endswith(_PINGGY_HOSTS) or host in _PINGGY_SKIP_HOSTS:
                continue                       # skips dashboard/docs links
            tunnel_url.append(f"https://{host}")

    threading.Thread(target=reader, daemon=True).start()
    for _ in range(60):
        if tunnel_url:
            app.say("warn", "pinggy free tunnels show a one-time screening page to browsers "
                            "— Discord's crawler gets that page too, so the embed image "
                            "may not render. Use cloudflared/localhost.run for clean previews.")
            app.say("net", "pinggy: tunnel expires in ~60 min (auto-renewed)")
            return proc, tunnel_url[0]
        if proc.poll() is not None:
            app.say("error", f"pinggy exited with code {proc.returncode}")
            break
        time.sleep(0.5)

    if not tunnel_url:
        app.say("error", "pinggy gave no URL (network/SSH blocked on port 443?)")
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        return None, None
    return proc, tunnel_url[0]


def start_serveo(port: int) -> tuple[subprocess.Popen | None, str | None]:
    """serveo.net — free, no signup, plain SSH. Free tier shows a warning page
    to visitors, so this is only a last-resort fallback."""
    if not shutil.which("ssh"):
        app.say("error", "ssh client not found — install openssh-client")
        return None, None

    proc = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes",
         "-R", f"80:127.0.0.1:{port}", "serveo.net"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=ROOT,
    )
    tunnel_url: list[str] = []
    pattern = re.compile(r"https://[a-z0-9-]+\.serveousercontent\.com")

    def reader(proc=proc, tunnel_url=tunnel_url) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if "Forwarding" not in line:
                continue
            match = pattern.search(line)
            if match and not tunnel_url:
                tunnel_url.append(match.group(0).rstrip("/,."))

    threading.Thread(target=reader, daemon=True).start()
    for _ in range(45):
        if tunnel_url:
            app.say("warn", "serveo: visitors may see a warning page first (free tier)")
            return proc, tunnel_url[0]
        if proc.poll() is not None:
            app.say("error", f"serveo exited with code {proc.returncode}")
            break
        time.sleep(0.5)

    if not tunnel_url:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        return None, None
    return proc, tunnel_url[0]


def ngrok_ready() -> bool:
    """ngrok v3 refuses to start without an authtoken — don't waste a cycle."""
    return bool(app.config.get("ngrokAuthtoken") or os.environ.get("NGROK_AUTHTOKEN"))


def launch_tunnel(kind: str, port: int) -> tuple[subprocess.Popen | None, str | None, str]:
    """Tries the requested tunnel, falling back through the others.

    Everything except ngrok needs no account. The default order puts the
    providers that pass traffic through untouched (Cloudflare, localhost.run)
    first: pinggy/serveo may show their own page to browsers first.
    """
    free = ["cloudflared", "ssh", "pinggy", "serveo"]
    if ngrok_ready():
        free.append("ngrok")
    order = {
        "auto": free,
        "cloudflared": ["cloudflared", "ssh", "pinggy", "serveo"],
        "pinggy": ["pinggy", "cloudflared", "ssh", "serveo"],
        "ssh": ["ssh", "cloudflared", "pinggy", "serveo"],
        "serveo": ["serveo", "ssh", "cloudflared", "pinggy"],
        "ngrok": (["ngrok"] if ngrok_ready() else []) + ["cloudflared", "ssh", "pinggy"],
        "none": [],
    }.get(kind, free)

    makers = {"cloudflared": start_cloudflared, "pinggy": start_pinggy,
              "ssh": start_ssh, "serveo": start_serveo, "ngrok": start_ngrok}

    for candidate in order:
        app.say("net", f"starting tunnel: {candidate}…")
        proc, url = makers[candidate](port)
        if url:
            return proc, url, candidate
        if proc is not None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
    return None, None, "none"


def self_test(base: str, attempts: int = 6, delay: float = 2.0) -> bool:
    """Verify the tunnel serves *this app*.

    A bare 200 proves nothing: landing pages and SPA fallbacks (as served by
    localhost.run) happily return 200 for any path, so the response body is
    checked for our /healthz JSON marker instead.

    Brand-new trycloudflare hostnames routinely take 60-90s before DNS starts
    answering, so every failed attempt records *why* it failed — a bare
    "FAILED" line is useless when the tunnel is actually fine.
    """
    started = time.time()
    last_error = "no attempt completed"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=15) as resp:
                body = resp.read(1000).decode("utf-8", "replace")
                try:
                    data = json.loads(body) if body else {}
                except ValueError:
                    data = {}
                if resp.status == 200 and data.get("ok") is True and data.get("app"):
                    app.say("net", f"self-test verified: {data['app']} "
                                   f"{str(data.get('version', '?')).lstrip('v')} "
                                   f"through the tunnel "
                                   f"({time.time() - started:.0f}s)")
                    return True
                last_error = (f"HTTP {resp.status} but the body is not this "
                              f"app: {body[:70]!r}")
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < attempts - 1:
            time.sleep(delay)
    app.say("warn", f"self-test gave up after {time.time() - started:.0f}s — "
                    f"last error: {last_error}")
    return False


def main() -> None:
    try:  # keep output visible even when redirected to a file
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Run the image logger + tunnel")
    parser.add_argument("--port", type=int, default=None, help="local port")
    parser.add_argument("--host", default=None, help="local bind address")
    parser.add_argument("--tunnel",
                        choices=["auto", "cloudflared", "pinggy", "ssh", "serveo", "ngrok", "none"],
                        default=None,
                        help="tunnel provider — all except ngrok need no login "
                             "(default: 'tunnel' from config.json, else auto)")
    parser.add_argument("--no-tunnel", action="store_true", help="local only")
    args = parser.parse_args()

    kind = args.tunnel or app.config.get("tunnel") or "auto"
    if args.no_tunnel:
        kind = "none"

    def shutdown(*_a) -> None:
        """SIGTERM -> unwind to the cleanup below (kills the tunnel too)."""
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)

    server = app.start_server(args.host, args.port)
    port = server.server_address[1]

    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5},
                     daemon=True).start()

    proc, tunnel_url, kind_used = (None, None, "none")
    fixed = (app.config.get("tunnelUrl") or "").strip().rstrip("/")
    if fixed and "://" not in fixed:
        fixed = "https://" + fixed
    if fixed.startswith("http") and kind != "none":
        # a fixed public front door already exists (Caddy, ngrok static domain,
        # a paid tunnel…) — advertise it instead of launching a new one
        app.say("net", f"using configured tunnel URL: {fixed}")
        tunnel_url, kind_used = fixed, "fixed"
    elif kind != "none":
        proc, tunnel_url, kind_used = launch_tunnel(kind, port)

    if tunnel_url:
        remember_tunnel_url(tunnel_url)

    local = f"http://{app.config['host']}:{port}"
    dash_path = (app.config.get("dashboard") or {}).get("path", "/dashboard")
    token = (app.config.get("dashboard") or {}).get("token") or ""
    dash_qs = f"?token={token}" if token else ""
    dash_local = f"{local}{dash_path}{dash_qs}"
    dash_public = f"{tunnel_url}{dash_path}{dash_qs}" if tunnel_url else None

    banner("IMAGE LOGGER IS LIVE")
    print(f"  local     {local}")
    if dash_public:
        app.PUBLIC_BASE = tunnel_url
        print(f"  \033[1;92mpublic    {tunnel_url}\033[0m")
        print(f"  \033[90mtunnel    {kind_used}  (URL changes on every restart; "
              f"also saved to logs/tunnel.url)\033[0m")
        print(f"  \033[1;93mdashboard {dash_public}\033[0m")
        print(f"  \033[90mlogs api  {tunnel_url}/api/logs?token={token}\033[0m")
        print("  \033[90ma brand-new URL may take ~30-90s to start resolving in "
              "DNS — the self-test below checks it for you\033[0m")
    else:
        print(f"  \033[1;93mdashboard {dash_local}\033[0m")
        if kind != "none":
            print("  \033[1;91mno tunnel URL was acquired — try "
                  "`python3 run.py --tunnel ngrok` or wait a minute "
                  "(Cloudflare rate-limits new quick tunnels)\033[0m")

    if tunnel_url:
        # brand-new trycloudflare hostnames can take a while to resolve in DNS,
        # so verify in the background instead of holding up the banner
        def run_self_test() -> None:
            # 40 x 3s = 120s: observed DNS lag for fresh quick-tunnel
            # hostnames runs 60-90s, so 60s used to fail on a healthy tunnel
            ok = self_test(tunnel_url, attempts=40, delay=3.0)
            if ok:
                print("  self-test \033[1;92mPASSED\033[0m — public link reaches "
                      "this server, it is live", flush=True)
            else:
                print("  self-test \033[1;91mFAILED\033[0m — the URL is not "
                      "reaching this server (yet)", flush=True)
                print("  \033[90mif the error above is DNS/SSL, the brand-new URL "
                      "just needs more time (~60-90s) — retry the link shortly. "
                      "If it persists, Ctrl+C and relaunch for a fresh URL; the "
                      "current one is always in logs/tunnel.url\033[0m",
                      flush=True)

        threading.Thread(target=run_self_test, daemon=True).start()

    webhook_state = "configured" if app.config.get("webhook") else "NOT configured"
    print(f"  webhook   {webhook_state}")
    print("  \033[90mshare the public link, then watch hits land in realtime\033[0m")
    print("  \033[90mCtrl+C to stop\033[0m\n")

    try:
        while True:
            time.sleep(1)
            if proc is not None and proc.poll() is not None:
                app.say("warn", "tunnel process died — restarting")
                time.sleep(3)
                proc, tunnel_url, kind_used = launch_tunnel(kind, port)
                if tunnel_url:
                    app.PUBLIC_BASE = tunnel_url
                    remember_tunnel_url(tunnel_url)
                    app.say("net", f"tunnel back up ({kind_used}): {tunnel_url}")
                else:
                    proc = None
                    app.say("error", "could not restart the tunnel — will retry in 30s")
                    time.sleep(30)
    except KeyboardInterrupt:
        app.say("net", "shutting down")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        server.shutdown()
        server.server_close()
        # the URL dies with the tunnel — never leave a dead link on disk
        try:
            os.unlink(os.path.join(ROOT, "logs", "tunnel.url"))
        except OSError:
            pass


if __name__ == "__main__":
    main()
