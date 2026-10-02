# Testing

> **Status:** this repository currently ships **no automated test suite**.
> The strategy below is what a contributor should build and what the project's
> own manual checks cover today. Every expectation stated here matches the
> current implementation of `main.py`.

## Ground rules

Tests use **only**:

- a private Discord test server;
- test accounts you control;
- **synthetic** images (generated or clearly fake);
- a local HTTP server;
- mock events;
- a mock webhook endpoint.

Never test against real users, real servers you do not own, or real personal
data. Consent applies to manual tests too.

## Current manual verification

What can be checked today without a test framework:

```bash
python3 -m py_compile main.py run.py setup.py     # syntax / import sanity
bash -n start.sh                                  # shell syntax
python3 run.py                                    # boots, acquires tunnel, self-test
```

End-to-end checks (all against your own instance):

| # | Check | Expected |
|---|---|---|
| 1 | Startup | Prints `local`, `public`, `dashboard`; self-test validates `/healthz` **body** |
| 2 | `/dashboard` without token | `401` |
| 3 | `/dashboard?token=…` | `200`, HTML > 5 KB |
| 4 | `/api/logs` without token | `401` |
| 5 | Crawler user-agent | Image bytes with an image content type |
| 6 | Preview validity | JPEG magic bytes at start and end |
| 7 | Human user-agent | `200` HTML page |
| 8 | Realtime feed | Counter increases after a visit |
| 9 | Geolocation | Coarse location resolved for a public test IP |
| 10 | Favicon requests | Return `204`, **not** archived as events |
| 11 | Archive growth | `logs/hits.jsonl` gains one line per event |
| 12 | Retention | Append a line with an old `ts`, restart → the line is pruned |
| 13 | Oversized POST | `Content-Length` over the cap → `413` |

> **Case-sensitivity note:** some tunnels lowercase response headers. When
> asserting `Content-Type`, look it up case-insensitively or the test fails
> against a working server.

## Recommended automated cases

| Case | Setup | Expectation |
|---|---|---|
| PNG request | Synthetic `.png`, correct `Accept` | Valid PNG bytes, `image/png` |
| JPG request | Synthetic `.jpg` | Valid JPEG, decodable |
| Unsupported file type | `.txt`/`.exe` request | `4xx`, nothing archived |
| Oversized body | `Content-Length` > `maxImageSizeMb` | `413 Payload Too Large` — rejected before the body is buffered |
| Oversized preview image | Image URL serving > `maxImageSizeMb` | Fetch refused, nothing cached |
| Missing attachment | Request with no image parameter | No event recorded |
| Malformed request | Broken headers/path | `4xx`, no traceback leaked to the client |
| Invalid authentication | Wrong/missing token | `401` on dashboard and API routes (constant-time compare) |
| Duplicate request | Same request sent twice | Two distinct events with unique ids — no cross-request de-duplication (by design) |
| Expired event | Archive line with `ts` older than `dataRetentionDays` | Removed at boot or the next hourly sweep |
| Tunnel unavailable | Stop the tunnel provider | Clear error; local mode still serves |
| Webhook revoked | Mock endpoint returning `404` | Worker disables itself and logs once |
| Webhook rate-limited | Mock endpoint returning `429` + `retry_after` | Backoff honoured, no burst |

## Mock webhook endpoint

Point `IMAGE_LOGGER_WEBHOOK` at a local sink instead of Discord:

```bash
python3 -m http.server 9999 --bind 127.0.0.1     # trivial sink for inspection
export IMAGE_LOGGER_WEBHOOK="http://127.0.0.1:9999/hook"
python3 run.py --no-tunnel
```

For realistic assertions, use a tiny handler that records the body, returns
`204`, and can be switched to return `404`/`429` to exercise the failure paths.

## Mock events

Generate synthetic events directly (no Discord involvement):

```bash
curl -H "User-Agent: Mozilla/5.0 (test-suite/1.0)" \
     -H "Cf-Connecting-Ip: 203.0.113.10" \
     "http://127.0.0.1:8080/"
```

`203.0.113.0/24` is RFC 5737 documentation space — always use reserved
ranges for synthetic addresses.

## Tunnel-unavailable test

```bash
python3 run.py --no-tunnel          # local only, must still serve
python3 run.py --tunnel none        # explicit disable
```

Then assert the launcher reports the failure clearly instead of printing a
URL it never verified.

## CI recommendations

- `py_compile` / import check on every PR
- Linter + formatter gate (choose one; document it in [CONTRIBUTING.md](../CONTRIBUTING.md))
- End-to-end smoke test against `--no-tunnel` only (no external providers in CI)
- Secret scanning on every commit
- No network calls to third-party geolocation/webhook APIs from CI — mock them
