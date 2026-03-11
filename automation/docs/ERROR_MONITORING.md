# Error Monitoring — Setup and Usage

This document describes how to configure and maintain the Sentry-based error
monitoring system for the Telegram bot.

---

## Overview

The error monitoring module (`app/services/error_monitoring.py`) integrates
[Sentry](https://sentry.io) to capture:

- **Uncaught exceptions** — any exception that escapes the main thread or a
  spawned thread.
- **Telegram handler runtime errors** — errors raised inside command/message
  handlers, routed through `python-telegram-bot`'s error handler callback.
- **Webhook processing failures** — exceptions thrown while processing an
  incoming update at `POST /telegram/{secret}`.

Every captured event is enriched with the Telegram update context (update ID,
user/chat ID, the command name, the message text, and callback data) as well
as the full stack trace.

---

## Prerequisites

- A Sentry account and a project created for this service.
- `sentry-sdk==2.23.1` is listed in `requirements.txt` and installed in the
  runtime environment (it is installed automatically on Railway / Heroku /
  Docker builds).

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SENTRY_DSN` | **Yes** (to enable) | *(empty)* | The DSN string from your Sentry project settings. |
| `SENTRY_ENVIRONMENT` | No | `development` | Environment tag shown in Sentry (e.g. `production`, `staging`). Falls back to `APP_ENV` then `ENVIRONMENT`. |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.0` | Float between `0.0` and `1.0`. Set to `1.0` to capture 100 % of transactions for performance monitoring. |

Set these in your `.env` file locally or in the Railway / hosting platform's
environment variable dashboard.

**Example `.env` snippet:**

```dotenv
SENTRY_DSN=https://[your-key]@[your-org].ingest.sentry.io/[project-id]
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
```

---

## Disabling Error Monitoring

If `SENTRY_DSN` is not set (or is an empty string), monitoring is **silently
disabled**.  The bot starts and runs normally; only a single log line is
printed:

```
Error monitoring disabled: SENTRY_DSN is not set.
```

This means no code changes are needed to run the bot without Sentry — simply
leave `SENTRY_DSN` unset in development or test environments.

---

## How It Works

### Initialisation

`init_error_monitoring()` is called once during the FastAPI lifespan startup
(`app/main.py`).  It:

1. Reads `SENTRY_DSN` from environment variables.
2. Initialises the Sentry SDK with the DSN, environment name, and traces
   sample rate.
3. Installs global exception hooks on `sys.excepthook` and
   `threading.excepthook` so that unhandled exceptions from any thread are
   automatically forwarded to Sentry.

### Telegram-Specific Capture

The `telegram_error_handler` registered in `app/bot.py` calls
`capture_telegram_runtime_error(update, error)` for every exception raised
inside a Telegram handler.  This function extracts the following fields from
the `Update` object and attaches them as Sentry context:

| Field | Source |
|---|---|
| `update_id` | `update.update_id` |
| `user_id` | `update.effective_user.id` |
| `username` | `update.effective_user.username` |
| `chat_id` | `update.effective_chat.id` |
| `command` | First token of `message.text` when it starts with `/` |
| `message_text` | `effective_message.text` (truncated to 1000 chars) |
| `callback_data` | `callback_query.data` (truncated to 1000 chars) |

### Webhook-Level Capture

Any exception thrown during `await telegram_app.process_update(update)` inside
`POST /telegram/{secret}` is also caught and forwarded to Sentry with the
same Telegram update context, tagged `component: telegram-webhook`.

---

## Testing Locally

You can verify the integration without a real Sentry account by using a
[Sentry test DSN](https://docs.sentry.io/platforms/python/#configure) or by
inspecting the stdout output:

```
Error monitoring enabled (environment=development)
```

Run the existing test suite to validate the monitoring helpers:

```bash
pytest tests/test_error_monitoring.py -v
```

---

## Maintenance

- **Rotate the DSN** — update `SENTRY_DSN` in all environments if the Sentry
  project is recreated or the DSN is compromised.
- **Adjust the sample rate** — increase `SENTRY_TRACES_SAMPLE_RATE` to capture
  more performance data; set it to `0.0` to disable performance monitoring
  while keeping error capture active.
- **Environment segmentation** — set `SENTRY_ENVIRONMENT` to different values
  per deployment (e.g. `staging`, `production`) to filter issues in the Sentry
  dashboard by environment.
- **sentry-sdk upgrades** — pin the version in `requirements.txt` and test
  before upgrading, as the SDK's `push_scope` API has changed across major
  versions.
