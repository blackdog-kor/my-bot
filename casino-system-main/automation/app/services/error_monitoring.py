import os
import sys
import threading
from typing import Any

try:
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None


_MONITORING_ENABLED = False


def _environment_name() -> str:
    return (
        os.getenv("SENTRY_ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    )


def _trim_text(value: str | None, max_len: int = 1000) -> str | None:
    if value is None:
        return None
    if len(value) <= max_len:
        return value
    return f"{value[:max_len]}...(truncated)"


def build_telegram_update_context(update: Any) -> dict:
    if update is None:
        return {"has_update": False}

    effective_user = getattr(update, "effective_user", None)
    effective_chat = getattr(update, "effective_chat", None)
    effective_message = getattr(update, "effective_message", None)
    text = getattr(effective_message, "text", None)
    callback_query = getattr(update, "callback_query", None)

    command = None
    if isinstance(text, str) and text.startswith("/"):
        command = text.split()[0]

    callback_data = getattr(callback_query, "data", None) if callback_query else None

    return {
        "has_update": True,
        "update_id": getattr(update, "update_id", None),
        "user_id": getattr(effective_user, "id", None),
        "username": getattr(effective_user, "username", None),
        "chat_id": getattr(effective_chat, "id", None),
        "command": command,
        "message_text": _trim_text(text),
        "callback_data": _trim_text(callback_data),
    }


def init_error_monitoring() -> bool:
    global _MONITORING_ENABLED

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        print("Error monitoring disabled: SENTRY_DSN is not set.")
        return False

    if sentry_sdk is None:
        print("Error monitoring disabled: sentry-sdk is not installed.")
        return False

    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))

    sentry_sdk.init(
        dsn=dsn,
        environment=_environment_name(),
        traces_sample_rate=traces_sample_rate,
    )
    _MONITORING_ENABLED = True
    _install_global_exception_hooks()
    print(f"Error monitoring enabled (environment={_environment_name()})")
    return True


def _install_global_exception_hooks():
    previous_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        capture_exception(
            exc_value,
            tags={"component": "python-runtime"},
            context={"exception_type": getattr(exc_type, "__name__", str(exc_type))},
        )
        previous_sys_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook

    if hasattr(threading, "excepthook"):
        previous_thread_hook = threading.excepthook

        def thread_hook(args):
            capture_exception(
                args.exc_value,
                tags={"component": "python-thread"},
                context={
                    "thread_name": getattr(args.thread, "name", "unknown"),
                    "exception_type": getattr(args.exc_type, "__name__", str(args.exc_type)),
                },
            )
            previous_thread_hook(args)

        threading.excepthook = thread_hook


def capture_exception(error: Exception, tags: dict | None = None, context: dict | None = None):
    if not _MONITORING_ENABLED or sentry_sdk is None:
        return

    with sentry_sdk.push_scope() as scope:
        for key, value in (tags or {}).items():
            scope.set_tag(str(key), str(value))

        if context:
            scope.set_context("runtime", context)

        sentry_sdk.capture_exception(error)


def capture_telegram_runtime_error(update: Any, error: Exception):
    capture_exception(
        error,
        tags={"component": "telegram-bot"},
        context={"telegram_update": build_telegram_update_context(update)},
    )
