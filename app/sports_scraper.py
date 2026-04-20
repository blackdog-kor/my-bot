"""
Sports Scraper: 스포츠 경기 일정 및 결과 자동 수집.

Free API 기반 (API-Football via api-sports.io) + 웹 스크래핑 폴백.
계정 차단 위험 0% — Telegram API 미사용.

소스:
- API-Football (api-sports.io) — 실시간 경기 일정/결과/통계
- 웹 폴백: ESPN, BBC Sport (httpx + BeautifulSoup)

환경변수:
- SPORTS_API_KEY: API-Football 키 (api-sports.io 무료 100req/day)
- SPORTS_LEAGUES: 리그 ID (쉼표 구분, 기본: EPL,LaLiga,SerieA,L1,BL)
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("sports_scraper")

# ── Constants ────────────────────────────────────────────────────────────────

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# Major league IDs (API-Football)
LEAGUE_NAMES: dict[int, str] = {
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    61: "Ligue 1",
    78: "Bundesliga",
    2: "UEFA Champions League",
    3: "UEFA Europa League",
    1: "FIFA World Cup",
    848: "AFC Champions League",
    292: "K League 1",
}

# Emoji mapping per league
LEAGUE_EMOJI: dict[int, str] = {
    39: "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    140: "🇪🇸",
    135: "🇮🇹",
    61: "🇫🇷",
    78: "🇩🇪",
    2: "🏆",
    3: "🏆",
    1: "🌍",
    848: "🏆",
    292: "🇰🇷",
}

# Web scraping sources (fallback)
WEB_SPORTS_SOURCES: list[dict[str, str]] = [
    {
        "name": "espn_soccer",
        "url": "https://www.espn.com/soccer/schedule",
        "selector_articles": ".Table__TR, .ScheduleTables .Table__TBODY tr",
        "selector_title": "td a, .AnchorLink",
        "selector_text": "td",
    },
    {
        "name": "bbc_sport",
        "url": "https://www.bbc.com/sport/football/scores-fixtures",
        "selector_articles": ".sp-c-fixture, .qa-match-block",
        "selector_title": ".sp-c-fixture__team-name, .gs-o-media__body",
        "selector_text": ".sp-c-fixture__number, .gs-u-display-none",
    },
]


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class Match:
    """Single match data."""

    match_id: int = 0
    league_id: int = 0
    league_name: str = ""
    home_team: str = ""
    away_team: str = ""
    match_date: datetime | None = None
    status: str = "NS"  # NS=Not Started, FT=Finished, LIVE, etc.
    home_score: int | None = None
    away_score: int | None = None
    venue: str = ""
    round_name: str = ""


@dataclass
class MatchStats:
    """Match statistics for analysis."""

    match_id: int = 0
    possession_home: int = 0
    possession_away: int = 0
    shots_home: int = 0
    shots_away: int = 0
    shots_on_target_home: int = 0
    shots_on_target_away: int = 0
    corners_home: int = 0
    corners_away: int = 0
    fouls_home: int = 0
    fouls_away: int = 0


@dataclass
class TeamStanding:
    """Team league standing."""

    team_name: str = ""
    rank: int = 0
    points: int = 0
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    form: str = ""  # e.g., "WWDLW"


@dataclass
class SportsData:
    """Aggregated sports data for content generation."""

    upcoming: list[Match] = field(default_factory=list)
    recent_results: list[Match] = field(default_factory=list)
    standings: list[TeamStanding] = field(default_factory=list)
    league_id: int = 0
    league_name: str = ""
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── API-Football Client ──────────────────────────────────────────────────────

def _get_league_ids() -> list[int]:
    """Parse configured league IDs."""
    raw = settings.sports_leagues.strip()
    if not raw:
        return [39, 140, 135, 61, 78]
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


async def _api_request(
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make authenticated request to API-Football."""
    api_key = settings.sports_api_key
    if not api_key:
        raise ValueError("SPORTS_API_KEY not configured")

    headers = {
        "x-apisports-key": api_key,
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{API_FOOTBALL_BASE}/{endpoint}",
            headers=headers,
            params=params or {},
        )
        resp.raise_for_status()
        data = resp.json()

    errors = data.get("errors")
    if errors and isinstance(errors, dict) and errors:
        raise ValueError(f"API-Football error: {errors}")

    return data


async def fetch_upcoming_matches(
    league_id: int,
    days_ahead: int = 7,
) -> list[Match]:
    """Fetch upcoming matches for a league.

    Args:
        league_id: API-Football league ID.
        days_ahead: Number of days to look ahead.

    Returns:
        List of upcoming Match objects.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime(
        "%Y-%m-%d"
    )
    season = datetime.now(timezone.utc).year

    try:
        data = await _api_request(
            "fixtures",
            params={
                "league": league_id,
                "season": season,
                "from": today,
                "to": end,
                "timezone": "Asia/Seoul",
            },
        )
    except Exception as e:
        logger.warning("API-Football fixtures 조회 실패 (league=%d): %s", league_id, e)
        return []

    matches: list[Match] = []
    for fix in data.get("response", []):
        fixture = fix.get("fixture", {})
        teams = fix.get("teams", {})
        league = fix.get("league", {})
        goals = fix.get("goals", {})

        dt_str = fixture.get("date", "")
        match_dt = None
        if dt_str:
            try:
                match_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        matches.append(
            Match(
                match_id=fixture.get("id", 0),
                league_id=league_id,
                league_name=league.get("name", LEAGUE_NAMES.get(league_id, "")),
                home_team=teams.get("home", {}).get("name", ""),
                away_team=teams.get("away", {}).get("name", ""),
                match_date=match_dt,
                status=fixture.get("status", {}).get("short", "NS"),
                home_score=goals.get("home"),
                away_score=goals.get("away"),
                venue=fixture.get("venue", {}).get("name", ""),
                round_name=league.get("round", ""),
            )
        )

    logger.info(
        "리그 %d (%s) 향후 경기 %d건 조회",
        league_id,
        LEAGUE_NAMES.get(league_id, ""),
        len(matches),
    )
    return matches


async def fetch_recent_results(
    league_id: int,
    days_back: int = 3,
) -> list[Match]:
    """Fetch recent match results for a league."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime(
        "%Y-%m-%d"
    )
    season = datetime.now(timezone.utc).year

    try:
        data = await _api_request(
            "fixtures",
            params={
                "league": league_id,
                "season": season,
                "from": start,
                "to": today,
                "status": "FT",
                "timezone": "Asia/Seoul",
            },
        )
    except Exception as e:
        logger.warning("API-Football 결과 조회 실패 (league=%d): %s", league_id, e)
        return []

    matches: list[Match] = []
    for fix in data.get("response", []):
        fixture = fix.get("fixture", {})
        teams = fix.get("teams", {})
        league = fix.get("league", {})
        goals = fix.get("goals", {})

        dt_str = fixture.get("date", "")
        match_dt = None
        if dt_str:
            try:
                match_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        matches.append(
            Match(
                match_id=fixture.get("id", 0),
                league_id=league_id,
                league_name=league.get("name", LEAGUE_NAMES.get(league_id, "")),
                home_team=teams.get("home", {}).get("name", ""),
                away_team=teams.get("away", {}).get("name", ""),
                match_date=match_dt,
                status="FT",
                home_score=goals.get("home"),
                away_score=goals.get("away"),
                venue=fixture.get("venue", {}).get("name", ""),
                round_name=league.get("round", ""),
            )
        )

    logger.info("리그 %d 최근 결과 %d건 조회", league_id, len(matches))
    return matches


async def fetch_standings(league_id: int) -> list[TeamStanding]:
    """Fetch current league standings."""
    season = datetime.now(timezone.utc).year

    try:
        data = await _api_request(
            "standings",
            params={"league": league_id, "season": season},
        )
    except Exception as e:
        logger.warning("API-Football 순위 조회 실패 (league=%d): %s", league_id, e)
        return []

    standings: list[TeamStanding] = []
    for league_data in data.get("response", []):
        for group in league_data.get("league", {}).get("standings", []):
            for team in group:
                all_stats = team.get("all", {})
                standings.append(
                    TeamStanding(
                        team_name=team.get("team", {}).get("name", ""),
                        rank=team.get("rank", 0),
                        points=team.get("points", 0),
                        played=all_stats.get("played", 0),
                        wins=all_stats.get("win", 0),
                        draws=all_stats.get("draw", 0),
                        losses=all_stats.get("lose", 0),
                        goals_for=all_stats.get("goals", {}).get("for", 0),
                        goals_against=all_stats.get("goals", {}).get("against", 0),
                        form=team.get("form", ""),
                    )
                )

    logger.info("리그 %d 순위표 %d팀 조회", league_id, len(standings))
    return standings


# ── Web Scraping Fallback ────────────────────────────────────────────────────

async def _scrape_sports_web() -> list[dict[str, Any]]:
    """Fallback: scrape sports schedules from free web sources."""
    from bs4 import BeautifulSoup

    results: list[dict[str, Any]] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    for source in WEB_SPORTS_SOURCES:
        try:
            async with httpx.AsyncClient(
                timeout=30.0, follow_redirects=True, headers=headers,
            ) as client:
                resp = await client.get(source["url"])
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            articles = soup.select(source["selector_articles"])[:20]

            for el in articles:
                title_el = el.select_one(source["selector_title"])
                text_el = el.select_one(source["selector_text"])
                title = title_el.get_text(strip=True) if title_el else ""
                text = text_el.get_text(strip=True) if text_el else ""

                if not title and not text:
                    continue

                results.append({
                    "text": f"{title}\n{text}".strip(),
                    "source": source["name"],
                    "type": "schedule",
                })

            logger.info("웹 스크래핑 %s: %d건", source["name"], len(articles))

        except Exception as e:
            logger.warning("웹 스크래핑 실패 (%s): %s", source["name"], e)

        await asyncio.sleep(random.uniform(2.0, 5.0))

    return results


# ── Public API ────────────────────────────────────────────────────────────────

async def collect_sports_data(league_id: int | None = None) -> list[SportsData]:
    """Collect comprehensive sports data for all configured leagues.

    Args:
        league_id: Specific league ID (None = all configured).

    Returns:
        List of SportsData per league.
    """
    league_ids = [league_id] if league_id else _get_league_ids()
    all_data: list[SportsData] = []

    for lid in league_ids:
        sd = SportsData(
            league_id=lid,
            league_name=LEAGUE_NAMES.get(lid, f"League {lid}"),
        )

        # Parallel fetch: upcoming + recent results + standings
        upcoming_task = fetch_upcoming_matches(lid)
        results_task = fetch_recent_results(lid)
        standings_task = fetch_standings(lid)

        upcoming, results, standings = await asyncio.gather(
            upcoming_task, results_task, standings_task,
            return_exceptions=True,
        )

        if isinstance(upcoming, list):
            sd.upcoming = upcoming
        else:
            logger.warning("경기 일정 조회 실패 (league=%d): %s", lid, upcoming)

        if isinstance(results, list):
            sd.recent_results = results
        else:
            logger.warning("최근 결과 조회 실패 (league=%d): %s", lid, results)

        if isinstance(standings, list):
            sd.standings = standings
        else:
            logger.warning("순위 조회 실패 (league=%d): %s", lid, standings)

        all_data.append(sd)

        # Rate limit (API-Football free: 100 req/day)
        await asyncio.sleep(random.uniform(1.0, 3.0))

    logger.info("전체 스포츠 데이터 수집 완료: %d개 리그", len(all_data))
    return all_data


async def collect_sports_data_web_fallback() -> list[dict[str, Any]]:
    """Web scraping fallback when API key is not available."""
    logger.info("SPORTS_API_KEY 미설정 — 웹 스크래핑 폴백 사용")
    return await _scrape_sports_web()
