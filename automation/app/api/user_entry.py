from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, field_validator

from app.config import INTEGRATION_SECRET
from app.db import has_entry_event, save_entry_event, upsert_user_entry

router = APIRouter()

VALID_GAME_CATEGORIES = {"slots", "casino", "sports", "unknown"}


class StartNormalized(BaseModel):
    source: str = "direct"
    campaign: str = ""
    promo_code: str = ""
    game_category: str = "unknown"

    @field_validator("game_category")
    @classmethod
    def normalize_game_category(cls, v: str) -> str:
        return v if v in VALID_GAME_CATEGORIES else "unknown"


class UserEntryPayload(BaseModel):
    event_id: str
    event_name: str
    event_version: str
    event_time: str
    entry_bot_name: str
    telegram_user_id: int
    telegram_username: str = ""
    offer_name: str
    start_raw: str
    start_normalized: StartNormalized


@router.post("/api/integration/user-entry")
async def user_entry(request: Request):
    secret = request.headers.get("X-Integration-Secret", "")
    if not INTEGRATION_SECRET or secret != INTEGRATION_SECRET:
        raise HTTPException(
            status_code=401,
            detail={
                "ok": False,
                "error": "unauthorized",
                "message": "Missing or invalid X-Integration-Secret header.",
            },
        )

    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": "validation_error",
                "message": "Request body must be valid JSON.",
            },
        )

    try:
        payload = UserEntryPayload(**raw)
    except Exception as exc:
        first_error = str(exc).split("\n")[0]
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": "validation_error",
                "message": first_error,
            },
        )

    print(
        f"[user-entry] event_id={payload.event_id} "
        f"telegram_user_id={payload.telegram_user_id} "
        f"entry_bot={payload.entry_bot_name}"
    )

    if has_entry_event(payload.event_id):
        print(f"[user-entry] idempotent replay for event_id={payload.event_id}")
        return {
            "ok": True,
            "event_id": payload.event_id,
            "user": {
                "telegram_user_id": payload.telegram_user_id,
                "created": False,
                "updated": False,
            },
            "idempotent_replay": True,
        }

    created, updated = upsert_user_entry(
        telegram_user_id=payload.telegram_user_id,
        username=payload.telegram_username,
        source=payload.start_normalized.source,
        campaign=payload.start_normalized.campaign,
        promo_code=payload.start_normalized.promo_code,
        game_category=payload.start_normalized.game_category,
        offer_name=payload.offer_name,
    )

    save_entry_event(payload.event_id, payload.telegram_user_id)

    return {
        "ok": True,
        "event_id": payload.event_id,
        "user": {
            "telegram_user_id": payload.telegram_user_id,
            "created": created,
            "updated": updated,
        },
        "idempotent_replay": False,
    }
