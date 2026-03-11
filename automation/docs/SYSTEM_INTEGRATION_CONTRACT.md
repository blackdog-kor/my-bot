# System Integration Contract

**Between:** `blackdog-kor/telegram-bot` → `blackdog-kor/sns-automation`

**Version:** 1.0.0  
**Status:** Implemented — runtime endpoint is live. See `app/api/user_entry.py`.

---

## Table of Contents

1. [Architecture Invariant](#1-architecture-invariant)
2. [Central User Key](#2-central-user-key)
3. [Mandatory Payload Fields](#3-mandatory-payload-fields)
4. [Deep-Link Normalization Rules](#4-deep-link-normalization-rules)
5. [Passing source / campaign / promo_code / game_category](#5-passing-source--campaign--promo_code--game_category)
6. [Duplicate Prevention / Idempotency](#6-duplicate-prevention--idempotency)
7. [Integration Authentication](#7-integration-authentication)
8. [Success / Failure Response Contract](#8-success--failure-response-contract)
9. [Non-Goals / Implementation Note](#9-non-goals--implementation-note)

---

## 1. Architecture Invariant

| System | Role |
|---|---|
| `blackdog-kor/telegram-bot` | **Entry bot only** — user-facing first contact and traffic entry point. Handles the Telegram `/start` command, normalizes deep-link parameters, and forwards structured events to `sns-automation`. |
| `blackdog-kor/sns-automation` | **Central DB + automation bot** — owns user records, attribution data, and all downstream automation pipelines. |

**These two systems must remain separate.** Merging or refactoring them into a single bot is explicitly out of scope and must not be done.

`telegram-bot` is a thin edge layer; it contains no persistent state. All durable state lives in `sns-automation`.

---

## 2. Central User Key

`telegram_user_id` (Telegram's numeric user identifier) is the **single central user key** shared between both systems.

### Dedup semantics

- A user record is uniquely identified by `telegram_user_id`.
- **First event:** creates a new user record.
- **Subsequent events for the same `telegram_user_id`:** updates `last_seen` and the latest attribution fields (`source`, `campaign`, `promo_code`, `game_category`). No duplicate user record is created.
- `telegram_username` is informational only and may change; it is never used as a key.

---

## 3. Mandatory Payload Fields

`telegram-bot` MUST send a JSON body to `sns-automation` containing at minimum the following fields.

### Field definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | `string` | **Mandatory** | Globally unique identifier for this event (e.g. UUIDv4). Used for idempotency. |
| `event_name` | `string` | Mandatory | Human-readable event name (e.g. `"user_start"`). |
| `event_version` | `string` | Mandatory | Schema version (e.g. `"1.0"`). |
| `event_time` | `string` | Mandatory | UTC timestamp in ISO 8601 format (e.g. `"2026-03-08T09:00:00Z"`). |
| `entry_bot_name` | `string` | **Mandatory** | Identifier of the sending bot (e.g. `"telegram-bot-prod"`). |
| `telegram_user_id` | `integer` | **Mandatory** | Telegram numeric user ID. Central user key. |
| `telegram_username` | `string` | Optional | Telegram @username. Use empty string `""` when absent. |
| `offer_name` | `string` | **Mandatory** | The offer or product the user entered through. |
| `start_raw` | `string` | Mandatory | Raw `/start` deep-link payload string as received from Telegram. |
| `start_normalized` | `object` | Mandatory | Normalized deep-link parameters (see §4). |
| `start_normalized.source` | `string` | Mandatory | Traffic source (default: `"direct"`). |
| `start_normalized.campaign` | `string` | Mandatory | Campaign identifier (default: `""`). |
| `start_normalized.promo_code` | `string` | Mandatory | Promotional code (default: `""`). |
| `start_normalized.game_category` | `string` | Mandatory | Game category (default: `"unknown"`). |

### Canonical JSON example

```json
{
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "event_name": "user_start",
  "event_version": "1.0",
  "event_time": "2026-03-08T09:00:00Z",
  "entry_bot_name": "telegram-bot-prod",
  "telegram_user_id": 123456789,
  "telegram_username": "john_doe",
  "offer_name": "summer_slots_2026",
  "start_raw": "src=google|cmp=summer2026|pc=PROMO10|gc=slots",
  "start_normalized": {
    "source": "google",
    "campaign": "summer2026",
    "promo_code": "PROMO10",
    "game_category": "slots"
  }
}
```

---

## 4. Deep-Link Normalization Rules

`telegram-bot` normalizes the raw `/start` payload **before** forwarding it to `sns-automation`. The normalized result is placed in `start_normalized`.

### Alias mapping

Short aliases used in deep-link URLs are expanded to their canonical names:

| Alias | Canonical field |
|---|---|
| `src` | `source` |
| `cmp` | `campaign` |
| `pc` | `promo_code` |
| `gc` | `game_category` |

### Defaults when absent

If a parameter is missing from the raw payload, the following defaults apply:

| Field | Default value |
|---|---|
| `source` | `"direct"` |
| `campaign` | `""` |
| `promo_code` | `""` |
| `game_category` | `"unknown"` |

### Allowed `game_category` values

| Value | Description |
|---|---|
| `slots` | Slot games |
| `casino` | Casino / table games |
| `sports` | Sports betting |
| `unknown` | Any other value or absent |

Any `gc` value not in `{slots, casino, sports}` MUST be normalized to `"unknown"`.

---

## 5. Passing source / campaign / promo_code / game_category

### Canonical deep-link format

Parameters are passed as a pipe-delimited string in the Telegram `/start` payload:

```
src=<source>|cmp=<campaign>|pc=<promo_code>|gc=<game_category>
```

**Example:**

```
/start src=google|cmp=summer2026|pc=PROMO10|gc=slots
```

- Parameters may appear in any order.
- Parameters may be omitted; defaults from §4 apply.
- No spaces around `=` or `|`.

---

## 6. Duplicate Prevention / Idempotency

Two independent dedup mechanisms are required.

### 6.1 User-level dedup by `telegram_user_id`

- `sns-automation` uses `telegram_user_id` as the primary key for the user table.
- The first event for a given `telegram_user_id` creates the user record.
- Every subsequent event for the same `telegram_user_id` updates attribution fields (`source`, `campaign`, `promo_code`, `game_category`) and `last_seen` timestamp. No new record is inserted.

### 6.2 Event-level idempotency by `event_id`

- `event_id` is mandatory and must be unique per logical event.
- `sns-automation` MUST store processed `event_id` values.
- If an event arrives with an `event_id` that has already been processed, `sns-automation` MUST return a success response with `"idempotent_replay": true` and MUST NOT perform any state mutation.

### Expected behavior summary

| Scenario | Action |
|---|---|
| New `telegram_user_id`, new `event_id` | Create user; process event normally |
| Existing `telegram_user_id`, new `event_id` | Update user attribution fields; process event normally |
| Any `telegram_user_id`, duplicate `event_id` | Return idempotent replay success; skip all processing |

---

## 7. Integration Authentication

All requests from `telegram-bot` to `sns-automation` MUST include the following HTTP header:

```
X-Integration-Secret: <shared_secret>
```

The shared secret is provisioned out-of-band (environment variable / secrets manager) and must not appear in source code.

### Behavior

| Condition | Result |
|---|---|
| Header present and secret valid | Request is processed normally |
| Header missing | `401 Unauthorized` — auth failure response |
| Header present but secret invalid | `401 Unauthorized` — auth failure response |

`sns-automation` MUST reject the request before any payload parsing or state mutation when the secret is missing or invalid.

---

## 8. Success / Failure Response Contract

All responses use `Content-Type: application/json`.

### 8.1 Status code mapping

| HTTP Status | Meaning |
|---|---|
| `200` | Success (including idempotent replay) |
| `400` | Validation error — malformed or missing required fields |
| `401` | Invalid or missing `X-Integration-Secret` |
| `409` | Contract violation (optional — use if a hard protocol invariant is broken) |
| `500` | Internal server error |

### 8.2 Success response

```json
{
  "ok": true,
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user": {
    "telegram_user_id": 123456789,
    "created": true,
    "updated": false
  },
  "idempotent_replay": false
}
```

- `created: true` — a new user record was inserted.
- `updated: true` — an existing user record was updated (attribution refresh).
- `created` and `updated` are mutually exclusive; both can be `false` only on idempotent replay.

### 8.3 Idempotent replay success response

```json
{
  "ok": true,
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user": {
    "telegram_user_id": 123456789,
    "created": false,
    "updated": false
  },
  "idempotent_replay": true
}
```

### 8.4 Failure responses

**401 — Invalid integration secret:**

```json
{
  "ok": false,
  "error": "unauthorized",
  "message": "Missing or invalid X-Integration-Secret header."
}
```

**400 — Validation error:**

```json
{
  "ok": false,
  "error": "validation_error",
  "message": "Missing required field: event_id."
}
```

**500 — Internal server error:**

```json
{
  "ok": false,
  "error": "internal_error",
  "message": "An unexpected error occurred."
}
```

---

## End-to-End Request Example

### Request

```http
POST /api/integration/user-entry HTTP/1.1
Host: sns-automation.example.com
Content-Type: application/json
X-Integration-Secret: supersecrettoken123

{
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "event_name": "user_start",
  "event_version": "1.0",
  "event_time": "2026-03-08T09:00:00Z",
  "entry_bot_name": "telegram-bot-prod",
  "telegram_user_id": 123456789,
  "telegram_username": "john_doe",
  "offer_name": "summer_slots_2026",
  "start_raw": "src=google|cmp=summer2026|pc=PROMO10|gc=slots",
  "start_normalized": {
    "source": "google",
    "campaign": "summer2026",
    "promo_code": "PROMO10",
    "game_category": "slots"
  }
}
```

### Response

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "ok": true,
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user": {
    "telegram_user_id": 123456789,
    "created": true,
    "updated": false
  },
  "idempotent_replay": false
}
```

---

## 9. Non-Goals / Implementation Note

- Runtime implementation: `POST /api/integration/user-entry` is live in `app/api/user_entry.py`.
- No DM sending logic is included in this implementation.
- No modifications were made under `telegram-bot`.

---

## 10. Telegram Bot Error Monitoring (`sns-automation`)

The runtime bot inside this repository supports optional Sentry-based error monitoring.

### Setup

Set the following environment variables:

- `SENTRY_DSN` (required to enable monitoring)
- `SENTRY_ENVIRONMENT` (optional, default: `development`)
- `SENTRY_TRACES_SAMPLE_RATE` (optional, default: `0.0`)

### What is captured

- Uncaught runtime exceptions (`sys.excepthook` / thread exceptions)
- Telegram handler runtime errors through the bot error handler
- Webhook processing failures in `POST /telegram/{secret}`

Each report includes Telegram update context where available (update id, user/chat id, command, input text, callback data) and stack traces.

### Behavior by environment

- Works in development/staging/production using the same integration.
- If `SENTRY_DSN` is not set, monitoring is disabled without affecting bot behavior.
