"""
Tests for POST /api/integration/user-entry endpoint.

A minimal FastAPI test app is created here so the tests do not depend on the
full telegram-bot lifespan (BOT_TOKEN, PUBLIC_BASE_URL, WEBHOOK_SECRET, etc.).
"""

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# --- Minimal test app --------------------------------------------------------

os.environ.setdefault("INTEGRATION_SECRET", "test-secret-123")

from app.api.user_entry import router  # noqa: E402 — import after env setup
from app.db import ensure_db  # noqa: E402

test_app = FastAPI()
test_app.include_router(router)
client = TestClient(test_app)

# --- Helpers -----------------------------------------------------------------

VALID_PAYLOAD = {
    "event_id": "aaaa-bbbb-cccc-dddd",
    "event_name": "user_start",
    "event_version": "1.0",
    "event_time": "2026-03-08T09:00:00Z",
    "entry_bot_name": "telegram-bot-prod",
    "telegram_user_id": 111222333,
    "telegram_username": "tester",
    "offer_name": "summer_slots_2026",
    "start_raw": "src=google|cmp=summer2026|pc=PROMO10|gc=slots",
    "start_normalized": {
        "source": "google",
        "campaign": "summer2026",
        "promo_code": "PROMO10",
        "game_category": "slots",
    },
}

HEADERS_OK = {"X-Integration-Secret": "test-secret-123"}


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Point the DB at a fresh temp file for every test."""
    import app.db as db_module

    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "DATA_DIR", str(tmp_path))
    ensure_db()
    yield


# --- Authentication ----------------------------------------------------------


def test_missing_secret_returns_401():
    resp = client.post("/api/integration/user-entry", json=VALID_PAYLOAD)
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["ok"] is False
    assert body["detail"]["error"] == "unauthorized"


def test_wrong_secret_returns_401():
    resp = client.post(
        "/api/integration/user-entry",
        json=VALID_PAYLOAD,
        headers={"X-Integration-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["error"] == "unauthorized"


# --- Validation --------------------------------------------------------------


def test_missing_required_field_returns_400():
    payload = {**VALID_PAYLOAD}
    del payload["event_id"]
    resp = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["ok"] is False
    assert body["detail"]["error"] == "validation_error"


def test_missing_telegram_user_id_returns_400():
    payload = {**VALID_PAYLOAD}
    del payload["telegram_user_id"]
    resp = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp.status_code == 400


def test_missing_offer_name_returns_400():
    payload = {**VALID_PAYLOAD}
    del payload["offer_name"]
    resp = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp.status_code == 400


# --- Success — new user ------------------------------------------------------


def test_new_user_returns_200_created():
    import uuid

    payload = {**VALID_PAYLOAD, "event_id": str(uuid.uuid4()), "telegram_user_id": 999001}
    resp = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["event_id"] == payload["event_id"]
    assert body["user"]["telegram_user_id"] == 999001
    assert body["user"]["created"] is True
    assert body["user"]["updated"] is False
    assert body["idempotent_replay"] is False


# --- Success — existing user update ------------------------------------------


def test_existing_user_returns_200_updated():
    import uuid

    user_id = 999002

    # First call — creates user
    first_payload = {**VALID_PAYLOAD, "event_id": str(uuid.uuid4()), "telegram_user_id": user_id}
    client.post("/api/integration/user-entry", json=first_payload, headers=HEADERS_OK)

    # Second call — updates user
    second_payload = {
        **VALID_PAYLOAD,
        "event_id": str(uuid.uuid4()),
        "telegram_user_id": user_id,
        "offer_name": "winter_casino_2026",
        "start_normalized": {
            "source": "facebook",
            "campaign": "winter2026",
            "promo_code": "",
            "game_category": "casino",
        },
    }
    resp = client.post("/api/integration/user-entry", json=second_payload, headers=HEADERS_OK)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["user"]["created"] is False
    assert body["user"]["updated"] is True
    assert body["idempotent_replay"] is False


# --- Idempotent replay -------------------------------------------------------


def test_duplicate_event_id_returns_idempotent_replay():
    import uuid

    payload = {**VALID_PAYLOAD, "event_id": str(uuid.uuid4()), "telegram_user_id": 999003}

    resp1 = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp1.status_code == 200
    assert resp1.json()["idempotent_replay"] is False

    resp2 = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["ok"] is True
    assert body2["idempotent_replay"] is True
    assert body2["user"]["created"] is False
    assert body2["user"]["updated"] is False


# --- game_category normalization ---------------------------------------------


def test_unknown_game_category_normalized():
    import uuid

    payload = {
        **VALID_PAYLOAD,
        "event_id": str(uuid.uuid4()),
        "telegram_user_id": 999004,
        "start_normalized": {
            "source": "direct",
            "campaign": "",
            "promo_code": "",
            "game_category": "poker",  # not in allowed set → normalized to "unknown"
        },
    }
    resp = client.post("/api/integration/user-entry", json=payload, headers=HEADERS_OK)
    assert resp.status_code == 200
    # Verify the stored game_category is "unknown"
    import app.db as db_module

    row = db_module.get_user(999004)
    assert row is not None
    # row: (user_id, username, join_time, source, campaign, promo_code, game_category, last_seen, offer_name)
    # The new columns are after source, so we check by unpacking
    assert row[6] == "unknown"
