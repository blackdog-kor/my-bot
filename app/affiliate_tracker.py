import json
import logging
import os

import httpx
import psycopg2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
AFFILIATE_WEBHOOK_SECRET = os.getenv("AFFILIATE_WEBHOOK_SECRET", "")

router = APIRouter(prefix="/api/affiliate", tags=["affiliate"])


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def ensure_affiliate_stats_table():
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_stats (
                id           SERIAL PRIMARY KEY,
                collected_at TIMESTAMPTZ DEFAULT NOW(),
                date_from    DATE NOT NULL,
                date_to      DATE NOT NULL,
                clicks       INTEGER DEFAULT 0,
                registrations INTEGER DEFAULT 0,
                ftd_count    INTEGER DEFAULT 0,
                deposits     NUMERIC(12,2) DEFAULT 0,
                revenue      NUMERIC(12,2) DEFAULT 0,
                commission   NUMERIC(12,2) DEFAULT 0,
                source       TEXT DEFAULT 'chrome',
                raw_json     TEXT
            )
        """)
        # links snapshot table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_links (
                id           SERIAL PRIMARY KEY,
                collected_at TIMESTAMPTZ DEFAULT NOW(),
                link_code    TEXT NOT NULL,
                source_id    INTEGER,
                clicks       INTEGER DEFAULT 0,
                registrations INTEGER DEFAULT 0,
                raw_json     TEXT
            )
        """)
        conn.commit()
        logger.info("affiliate tables ready")
    except Exception:
        conn.rollback()
        logger.exception("ensure_affiliate_stats_table failed")
        raise
    finally:
        conn.close()


def save_affiliate_snapshot(stats: dict, links: list[dict] | None = None) -> int:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO affiliate_stats
              (date_from, date_to, clicks, registrations, ftd_count,
               deposits, revenue, commission, source, raw_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            stats.get("date_from"),
            stats.get("date_to"),
            stats.get("clicks", 0),
            stats.get("registrations", 0),
            stats.get("ftd_count", 0),
            stats.get("deposits", 0),
            stats.get("revenue", 0),
            stats.get("commission", 0),
            stats.get("source", "chrome"),
            json.dumps(stats),
        ))
        row_id = cur.fetchone()[0]

        if links:
            for lnk in links:
                cur.execute("""
                    INSERT INTO affiliate_links
                      (link_code, source_id, clicks, registrations, raw_json)
                    VALUES (%s,%s,%s,%s,%s)
                """, (
                    lnk.get("code", ""),
                    lnk.get("source_id"),
                    lnk.get("clicks", 0),
                    lnk.get("registrations", 0),
                    json.dumps(lnk),
                ))
        conn.commit()
        return row_id
    except Exception:
        conn.rollback()
        logger.exception("save_affiliate_snapshot failed")
        raise
    finally:
        conn.close()


def get_recent_stats(limit: int = 7) -> list[dict]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, collected_at, date_from, date_to,
                   clicks, registrations, ftd_count,
                   deposits, revenue, commission, source
            FROM affiliate_stats
            ORDER BY collected_at DESC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ── Pydantic models ──────────────────────────────────────────────────────────

class AffiliateStatsPayload(BaseModel):
    secret: str = ""
    date_from: str
    date_to: str
    clicks: int = 0
    registrations: int = 0
    ftd_count: int = 0
    deposits: float = 0
    revenue: float = 0
    commission: float = 0
    source: str = "chrome"
    links: list[dict] = []
    extra: dict = {}


# ── API endpoints ────────────────────────────────────────────────────────────

@router.post("/stats")
async def receive_stats(payload: AffiliateStatsPayload):
    """Chrome용 Claude or any client POSTs daily stats here."""
    if not AFFILIATE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if payload.secret != AFFILIATE_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    data = payload.model_dump()
    data.update(payload.extra)

    try:
        row_id = save_affiliate_snapshot(data, payload.links or [])
    except Exception as exc:
        logger.exception("Failed to save affiliate stats")
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("Affiliate snapshot saved: id=%s clicks=%s reg=%s commission=%s",
                row_id, payload.clicks, payload.registrations, payload.commission)

    # notify admin via Telegram if BOT_TOKEN + ADMIN_ID set
    _notify_admin(payload)

    return {"ok": True, "id": row_id}


@router.get("/report")
async def get_report(limit: int = 7):
    """Returns recent affiliate stats snapshots."""
    try:
        rows = get_recent_stats(limit)
        return {"ok": True, "count": len(rows), "data": rows}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _notify_admin(payload: AffiliateStatsPayload):
    bot_token = os.getenv("BOT_TOKEN", "")
    admin_id  = os.getenv("ADMIN_ID", "")
    if not bot_token or not admin_id:
        return
    try:
        msg = (
            f"📊 *1win 어필리에이트 일일 리포트*\n"
            f"기간: {payload.date_from} ~ {payload.date_to}\n\n"
            f"클릭: {payload.clicks:,}\n"
            f"가입: {payload.registrations:,}\n"
            f"첫입금(FTD): {payload.ftd_count:,}\n"
            f"총입금: ${payload.deposits:,.2f}\n"
            f"수익: ${payload.revenue:,.2f}\n"
            f"커미션: ${payload.commission:,.2f}"
        )
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": admin_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        logger.exception("Admin notify failed")
