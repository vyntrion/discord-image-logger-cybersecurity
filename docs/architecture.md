# Architecture

All diagrams are conceptual and defensive: they describe how data flows through
**your own** authorized environment, not how to reach anyone else's.

## 1. Overall architecture

```mermaid
flowchart TB
    subgraph Edge["Public edge (development tunnel)"]
        TUN["Tunnel endpoint<br/>HTTPS"]
    end

    subgraph Local["Loopback host 127.0.0.1"]
        HTTP["HTTP server<br/>routing + auth"]
        PROC["Event processor"]
        GEO["Geolocation worker"]
        WH["Webhook worker"]
        DASH["Dashboard<br/>SSE + polling"]
        ARCH[("JSONL archive")]
    end

    subgraph Third["Third-party services"]
        GEOAPI["Geolocation API"]
        DISC["Operator's Discord webhook"]
    end

    Client["Consented client"] -->|HTTPS| TUN
    Operator["Operator"] -->|token-gated| TUN
    TUN --> HTTP
    HTTP --> DASH
    HTTP --> PROC
    PROC --> ARCH
    PROC --> GEO
    GEO --> GEOAPI
    PROC --> WH
    WH --> DISC
```

| Component | Responsibility |
|---|---|
| **HTTP server** | Routes crawler vs. human traffic, enforces `dashboard.token`, answers immediately |
| **Event processor** | Normalizes a request into a structured event; drops noise (favicon requests) |
| **Geolocation worker** | Coarse enrichment from a public API, paced and cached |
| **Webhook worker** | Queued outbound embeds, honours `429 retry_after`, self-disables when the webhook is revoked |
| **JSONL archive** | Append-only history, replayed into the dashboard on restart |
| **Dashboard** | Realtime view; SSE primary with automatic polling fallback |
| **Tunnel** | Public HTTPS to a loopback service during development |

## 2. Discord event flow

```mermaid
sequenceDiagram
    participant C as Consented client
    participant T as Tunnel
    participant S as HTTP server
    participant P as Event processor
    participant G as Geolocation worker
    participant A as JSONL archive
    participant W as Webhook worker
    participant D as Discord webhook

    C->>T: GET / (HTTPS)
    T->>S: forward request
    alt crawler user-agent (link preview)
        S-->>C: image bytes (preview mode)
    else human visitor
        S-->>C: page (200, immediate)
    end
    S->>P: emit raw event
    P->>A: append JSONL
    P->>G: request enrichment (queued)
    G->>G: pace + cache
    G-->>P: coarse location (or "unavailable")
    P->>W: queue notification
    W->>D: POST embed (retry on 429)
    D-->>W: 204 / 404
    Note over W: 401/403/404 → disable, log once
```

Key property: **the client is never blocked** by geolocation or webhook
delivery — both happen on background workers.

## 3. HTTP / tunnel flow

```mermaid
flowchart LR
    A["Public client<br/>https://xyz.provider.tld"] -->|TLS| EDGE["Provider edge<br/>(TLS termination)"]
    EDGE -->|"encrypted tunnel<br/>(cloudflared / SSH reverse forward)"| LOCAL["127.0.0.1:8080"]
    LOCAL --> APP["main.py handler"]
    APP -->|"/healthz JSON"| SELF["Startup self-test<br/>(validates body, not just 200)"]
    APP -->|"?token=…"| ADMIN["Dashboard / API"]
    APP -->|everything else| LOGPAGE["Image / page + event"]
```

Notes:

- The service binds loopback only; the tunnel is the sole ingress.
- Providers change the hostname on restart — never hardcode a public URL.
- The self-test exists because some providers return `200` landing pages for
  unknown paths; only a body check proves the request reached *this* app.

## 4. Security boundary

```mermaid
flowchart TB
    subgraph Untrusted["Untrusted zone"]
        C[Public client]
        PEER["Provider edge (third party)"]
    end

    subgraph Trusted["Operator-controlled zone"]
        TUN["Tunnel client process"]
        subgraph Loop["Loopback only 127.0.0.1"]
            HTTP["HTTP server"]
            DASH["Dashboard/API<br/>requires token"]
            WORK["Geo + webhook workers"]
            FS[("logs/*.jsonl")]
        end
    end

    subgraph Third["Third-party APIs"]
        GEOAPI["Geolocation API"]
        DISC["Discord webhook"]
    end

    C --> PEER --> TUN --> HTTP
    HTTP -->|"401 without token"| DASH
    HTTP --> WORK
    WORK --> GEOAPI
    WORK --> DISC
    HTTP --> FS
```

**Boundary rules**

- Everything left of `TUN` is untrusted input.
- `DASH`/API routes are gated by `dashboard.token` → HTTP 401.
- `FS` holds collected data: git-ignored, protected, subject to retention.
- Outbound calls carry only what the notification needs — no tokens inbound.

## 5. Data lifecycle

```mermaid
flowchart LR
    IN["Request arrives"] --> CLASS{"Classify"}
    CLASS -->|crawler| PREVIEW["Serve preview image"]
    CLASS -->|human| PAGE["Serve page"]
    CLASS -->|favicon| DROP["204 — not an event"]
    PREVIEW --> RAW["Raw event"]
    PAGE --> RAW
    RAW --> ARCH[("append JSONL")]
    RAW --> ENRICH["Enrich (paced geo)"]
    ENRICH --> ENRICHED["Enriched event"]
    ENRICHED --> ARCH
    ENRICHED --> NOTIFY["Notify webhook"]
    ARCH --> RESTORE["Replay on restart"]
    ARCH --> RETAIN{"Retention policy"}
    RETAIN -->|"within window"| KEEP["Keep"]
    RETAIN -->|"expired / on request"| DELETE["Delete — [VERIFY AGAINST IMPLEMENTATION]"]
    NOTIFY --> REVOKE["Revoke webhook / rotate secrets"]
```

**Lifecycle controls that exist today:** append-only archive, replay on
restart, secret rotation by editing `config.json`, webhook self-disable on
revocation.

**Lifecycle controls to implement:** automatic age-based deletion
(`DATA_RETENTION_DAYS`), per-participant deletion requests, and audit logging.
Marked **[VERIFY AGAINST IMPLEMENTATION]** — see [privacy.md](privacy.md).
