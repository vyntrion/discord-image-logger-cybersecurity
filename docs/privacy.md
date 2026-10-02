# Privacy

This project records data about people. Treat that as a responsibility, not a
feature.

## What is collected

| Data | Why | Where |
|---|---|---|
| Client IP address | Core of the authorized exercise | `logs/hits.jsonl` |
| Coarse geolocation (city/region/country/ISP, sometimes lat/lon) | Enrichment from a **public geolocation API** | archive + dashboard |
| User-agent family (OS/browser, crawler vs. human) | Traffic classification | archive |
| Request path and timestamp | Event context | archive |
| Optional precise coordinates | **Only** if `accurateLocation` is enabled *and* the visitor accepts the browser prompt | transient event field |

## What is not collected (by design)

- Message content or channel history
- Credentials, tokens, cookies, or browser storage
- Files from the visitor's device
- Any Discord identifier in the webhook path

> **No inbound bot exists in this build.** Discord integration is a single
> outbound webhook, so nothing ever reads messages or attachments. If your
> fork adds a bot that touches attachments, document exactly which fields it
> records and update this page before publishing.

## Core principles

1. **Consent first.** Do not collect images or events from anyone who has not
   been told, in plain language, what happens, why, and for how long — and who
   has agreed. Consent must be revocable.
2. **Minimize.** Collect the least that satisfies the exercise. Do not store
   message content you do not need; avoid Discord identifiers entirely unless
   the exercise requires them.
3. **Shortest retention.** Default policy: **7 days**. Recommended: the
   shortest window that meets your goal. Do not keep data "just in case".
4. **Deletion on request.** Participants should be able to ask for removal,
   and you should be able to do it. Provide a documented path:
   stop the service → delete matching entries from `logFile` → restart →
   confirm. Age-based deletion is handled for you (see below); on-request
   deletion is still a manual, documented step.
5. **Protect the archive.** `logs/` is git-ignored. Keep the directory
   permission-restricted, do not sync it to shared drives without review, and
   never attach it to issues or support requests.
6. **Never publish collected data.** No screenshots of real events, no real
   IPs, no real Discord IDs in READMEs, issues, PRs, wikis, or social posts.
7. **Synthetic images only** in every example, test, and screenshot.

## Accurate location

`accurateLocation` triggers the browser's geolocation permission prompt. The
visitor sees a dialog and must accept — it is not silent tracking. Even so:

- keep it **off** unless the exercise genuinely needs street-level data;
- get explicit consent beforehand;
- record nothing beyond what the exercise needs;
- delete it promptly.

## Disclosure to participants

Before running anything, tell the test server:

- that image/link events are processed;
- which fields are recorded (IP, coarse location, user agent);
- where data is stored and for how long;
- how to opt out or request deletion.

## Geolocation provider

Enrichment calls a third-party geolocation API with the client IP. That
provider therefore learns which IPs your lab sees. Review its privacy policy;
use no-API-key endpoints where possible; keep lookups paced and cached (the
worker already does).

## Retention and deletion

| | |
|---|---|
| Default | 7 days (`dataRetentionDays`) |
| Recommended | Shortest necessary |
| Enforcement today | **Automatic.** `prune_archive()` runs at boot and then hourly, dropping every archive entry older than the window — under the archive lock, so live writes are never corrupted. Set `DATA_RETENTION_DAYS=0` to keep everything. |
| On-request deletion | Stop service → remove the participant's entries from `logs/hits.jsonl` → restart → log what was deleted |

## Review checklist

- [ ] Consent documented before the first event
- [ ] Retention window decided and written down
- [ ] `logs/` git-ignored and permission-protected
- [ ] No personal data in the repository or docs
- [ ] Deletion procedure tested
- [ ] `accurateLocation` off unless consented
- [ ] Screenshots use synthetic data only
