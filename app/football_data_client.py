"""
Football-Data.org API client (free tier, current season).

Free plan: 10 competitions, 10 calls/min.
Register at api.football-data.org to get a free API key.
Set env var: FOOTBALL_DATA_API_KEY=<your-key>

Competitions covered (free tier):
  PL=39, PD=140, SA=135, BL1=78, FL1=61, CL=2, EL=3, WC=1 (mapped)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger
from app.sports_scraper import (
    LEAGUE_EMOJI,
    LEAGUE_NAMES,
    Match,
    SportsData,
    TeamStanding,
)

logger = get_logger("football_data_client")

BASE_URL = "https://api.football-data.org/v4"

# Map our API-Football league IDs → Football-Data.org competition codes
LEAGUE_TO_FD_CODE: dict[int, str] = {
    39: "PL",    # Premier League
    140: "PD",   # La Liga
    135: "SA",   # Serie A
    78: "BL1",   # Bundesliga
    61: "FL1",   # Ligue 1
    2: "CL",     # Champions League
    3: "EL",     # Europa League
    1: "WC",     # FIFA World Cup
    88: "DED",   # Eredivisie
    94: "PPL",   # Primeira Liga
}

FD_STATUS_MAP = {
    "SCHEDULED": "NS",
    "LIVE": "1H",
    "IN_PLAY": "1H",
    "PAUSED": "HT",
    "FINISHED": "FT",
    "POSTPONED": "PST",
    "CANCELLED": "CANC",
}


async def _fd_request(path: str, params: dict | None = None) -> dict[str, Any]:
    """Authenticated GET to Football-Data.org."""
    api_key = settings.football_data_api_key
    if not api_key:
        raise ValueError("FOOTBALL_DATA_API_KEY not set")
    headers = {"X-Auth-Token": api_key, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{BASE_URL}{path}", headers=headers, params=params or {})
    if resp.status_code == 429:
        raise ValueError("Football-Data.org rate limit — try again in 60s")
    if resp.status_code == 403:
        raise ValueError(f"Football-Data.org 403: competition may require paid plan")
    resp.raise_for_status()
    remaining = resp.headers.get("X-Requests-Available-Minute", "?")
    logger.debug("FD API %s → %d (req remaining/min: %s)", path, resp.status_code, remaining)
    return resp.json()


def _parse_match(m: dict, league_id: int) -> Match:
    """Convert Football-Data.org match object to our Match dataclass."""
    home = m.get("homeTeam", {}).get("name", "")
    away = m.get("awayTeam", {}).get("name", "")
    utc_date = m.get("utcDate", "")
    match_dt = None
    if utc_date:
        try:
            match_dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        except ValueError:
            pass
    status_raw = m.get("status", "SCHEDULED")
    status = FD_STATUS_MAP.get(status_raw, status_raw)
    score = m.get("score", {}).get("fullTime", {})
    home_score = score.get("home")
    away_score = score.get("away")
    competition = m.get("competition", {})
    return Match(
        match_id=m.get("id", 0),
        league_id=league_id,
        league_name=competition.get("name", LEAGUE_NAMES.get(league_id, "")),
        home_team=home,
        away_team=away,
        match_date=match_dt,
        status=status,
        home_score=home_score,
        away_score=away_score,
        venue=m.get("venue", "") or "",
        round_name=m.get("matchday", "") and f"Matchday {m['matchday']}" or "",
    )


async def fetch_league_data(league_id: int, days_ahead: int = 7, days_back: int = 3) -> SportsData:
    """Fetch upcoming + recent matches + standings for one league."""
    code = LEAGUE_TO_FD_CODE.get(league_id)
    if not code:
        raise ValueError(f"No Football-Data.org code for league_id={league_id}")

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    sd = SportsData(
        league_id=league_id,
        league_name=LEAGUE_NAMES.get(league_id, code),
    )

    try:
        data = await _fd_request(f"/competitions/{code}/matches", {"dateFrom": date_from, "dateTo": date_to})
        matches = data.get("matches", [])
        for m in matches:
            parsed = _parse_match(m, league_id)
            if m.get("status") == "FINISHED":
                sd.recent_results.append(parsed)
            elif m.get("status") in ("SCHEDULED", "TIMED"):
                sd.upcoming.append(parsed)
        logger.info("FD %s: %d upcoming / %d results", code, len(sd.upcoming), len(sd.recent_results))
    except Exception as e:
        logger.warning("FD fetch failed (%s): %s", code, e)

    try:
        standings_data = await _fd_request(f"/competitions/{code}/standings")
        for table in standings_data.get("standings", []):
            if table.get("type") == "TOTAL":
                for row in table.get("table", [])[:10]:
                    team = row.get("team", {})
                    sd.standings.append(TeamStanding(
                        team_name=team.get("name", ""),
                        rank=row.get("position", 0),
                        played=row.get("playedGames", 0),
                        wins=row.get("won", 0),
                        draws=row.get("draw", 0),
                        losses=row.get("lost", 0),
                        goals_for=row.get("goalsFor", 0),
                        goals_against=row.get("goalsAgainst", 0),
                        points=row.get("points", 0),
                    ))
                break
    except Exception as e:
        logger.warning("FD standings failed (%s): %s", code, e)

    return sd


async def collect_sports_data_fd(
    league_ids: list[int] | None = None,
    days_ahead: int = 7,
) -> list[SportsData]:
    """Collect sports data from Football-Data.org for all configured leagues.

    Only attempts leagues that have a known Football-Data.org competition code.
    Returns list[SportsData] in the same format as API-Football path.
    """
    from app.sports_scraper import _get_league_ids
    ids = league_ids or _get_league_ids()
    supported = [lid for lid in ids if lid in LEAGUE_TO_FD_CODE]

    if not supported:
        logger.warning("No configured leagues have Football-Data.org codes: %s", ids)
        return []

    results: list[SportsData] = []
    for lid in supported:
        try:
            sd = await fetch_league_data(lid, days_ahead=days_ahead)
            results.append(sd)
        except Exception as e:
            logger.warning("FD league %d skipped: %s", lid, e)
        await asyncio.sleep(1.0)  # 10 calls/min rate limit

    logger.info("Football-Data.org collected: %d leagues", len(results))
    return results
