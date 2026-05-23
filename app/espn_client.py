"""
ESPN unofficial API client for non-EU leagues (free, no auth required).

Covers: MLS (253), J1 League (98), Brasileirao (71).
K League (292) is NOT in ESPN's 251-league catalog — excluded.
Odds embedded in scoreboard are American format, converted to decimal.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.logging_config import get_logger
from app.sports_scraper import LEAGUE_NAMES, Match, SportsData

logger = get_logger("espn_client")

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# API-Football league_id → ESPN scoreboard slug
LEAGUE_TO_ESPN: dict[int, str] = {
    253: "usa.1",   # MLS
    98:  "jpn.1",   # J1 League
    71:  "bra.1",   # Brasileirao Série A
}

_STATUS_MAP = {
    "STATUS_SCHEDULED": "NS", "STATUS_TIMED": "NS",
    "STATUS_IN_PROGRESS": "1H", "STATUS_HALFTIME": "HT",
    "STATUS_FINAL": "FT", "STATUS_POSTPONED": "PST",
    "STATUS_CANCELED": "CANC", "STATUS_SUSPENDED": "SUSP",
}


def _american_to_decimal(odds_str: str | int | float) -> float:
    """Convert American-format odds string/int to decimal odds."""
    try:
        n = int(str(odds_str).replace("+", ""))
        if n > 0:
            return round(n / 100 + 1, 2)
        if n < 0:
            return round(100 / abs(n) + 1, 2)
    except (ValueError, ZeroDivisionError):
        pass
    return 0.0


def _parse_odds(odds_list: list) -> dict[str, float]:
    """Extract decimal 1X2 + O/U 2.5 from ESPN embedded DraftKings odds."""
    for entry in odds_list:
        if not isinstance(entry, dict):
            continue
        ml = entry.get("moneyline") or {}
        home_raw = (ml.get("home") or {}).get("close", {}).get("odds", "")
        away_raw = (ml.get("away") or {}).get("close", {}).get("odds", "")
        draw_int = (entry.get("drawOdds") or {}).get("moneyLine", 0)
        total = entry.get("total") or {}
        over_raw = (total.get("over") or {}).get("close", {}).get("odds", "")
        under_raw = (total.get("under") or {}).get("close", {}).get("odds", "")

        home_w = _american_to_decimal(home_raw) if home_raw else 0.0
        away_w = _american_to_decimal(away_raw) if away_raw else 0.0
        if home_w and away_w:
            return {
                "home_win": home_w,
                "away_win": away_w,
                "draw": _american_to_decimal(draw_int) if draw_int else 0.0,
                "over_2_5": _american_to_decimal(over_raw) if over_raw else 0.0,
                "under_2_5": _american_to_decimal(under_raw) if under_raw else 0.0,
            }
    return {}


def _parse_event(
    event: dict, league_id: int,
) -> tuple[Match, dict[str, float]] | None:
    """Parse one ESPN event dict into (Match, odds_dict). Returns None on error."""
    try:
        comps = event.get("competitions", [])
        if not comps:
            return None
        comp = comps[0]

        home = away = ""
        home_score = away_score = None
        for c in comp.get("competitors", []):
            name = (c.get("team") or {}).get("displayName", "")
            score_str = c.get("score")
            score = int(score_str) if score_str is not None else None
            if c.get("homeAway") == "home":
                home, home_score = name, score
            else:
                away, away_score = name, score

        utc_str = event.get("date", "")
        match_dt: datetime | None = None
        if utc_str:
            try:
                match_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        status_raw = (event.get("status") or {}).get("type", {}).get("name", "STATUS_SCHEDULED")
        status = _STATUS_MAP.get(status_raw, status_raw)
        is_final = status in ("FT", "AET", "PEN")

        notes = comp.get("notes") or []
        round_name = notes[0].get("headline", "") if notes else ""
        odds = _parse_odds(comp.get("odds") or [])

        match = Match(
            match_id=int(event.get("id", 0)),
            league_id=league_id,
            league_name=LEAGUE_NAMES.get(league_id, ""),
            home_team=home,
            away_team=away,
            match_date=match_dt,
            status=status,
            home_score=home_score if is_final else None,
            away_score=away_score if is_final else None,
            venue=(comp.get("venue") or {}).get("fullName", ""),
            round_name=round_name,
        )
        return match, odds
    except Exception as e:
        logger.debug("ESPN parse_event failed: %s", e)
        return None


async def fetch_league_data_espn(league_id: int) -> SportsData:
    """Fetch matches for one ESPN-supported league.

    Attaches ``espn_odds: dict[int, dict[str, float]]`` on the returned SportsData,
    keyed by match_id, containing {home_win, away_win, draw, over_2_5, under_2_5}.
    """
    slug = LEAGUE_TO_ESPN.get(league_id)
    if not slug:
        raise ValueError(f"League {league_id} not in ESPN catalog")

    sd = SportsData(
        league_id=league_id,
        league_name=LEAGUE_NAMES.get(league_id, slug),
    )
    sd.espn_odds: dict[int, dict[str, float]] = {}  # type: ignore[attr-defined]

    url = f"{_BASE}/{slug}/scoreboard"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                url, params={"limit": 50},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("ESPN %s scoreboard failed: %s", slug, e)
            return sd

    for event in data.get("events", []):
        result = _parse_event(event, league_id)
        if not result:
            continue
        match, odds = result
        if match.status == "FT":
            sd.recent_results.append(match)
        elif match.status in ("NS", "1H", "HT", "2H"):
            sd.upcoming.append(match)
        if odds:
            sd.espn_odds[match.match_id] = odds  # type: ignore[attr-defined]

    logger.info("ESPN %s: %d upcoming / %d results", slug, len(sd.upcoming), len(sd.recent_results))
    return sd


async def collect_sports_data_espn(
    league_ids: list[int] | None = None,
) -> list[SportsData]:
    """Concurrently fetch all ESPN-supported leagues. Returns list[SportsData]."""
    ids = league_ids or list(LEAGUE_TO_ESPN.keys())
    supported = [lid for lid in ids if lid in LEAGUE_TO_ESPN]
    if not supported:
        logger.info("No ESPN-supported leagues in request: %s", ids)
        return []

    results = await asyncio.gather(
        *[fetch_league_data_espn(lid) for lid in supported],
        return_exceptions=True,
    )
    out: list[SportsData] = []
    for lid, res in zip(supported, results):
        if isinstance(res, Exception):
            logger.warning("ESPN league %d failed: %s", lid, res)
        else:
            out.append(res)

    logger.info("ESPN collected: %d leagues", len(out))
    return out
