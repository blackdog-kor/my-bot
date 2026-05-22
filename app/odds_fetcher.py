"""
Odds Fetcher: real-time betting odds via The Odds API (free tier: 500 req/month).

Provides 1X2 (h2h), Over/Under 2.5, and BTTS markets for major leagues.
Falls back gracefully when API key is missing or quota is exceeded.

Env: ODDS_API_KEY  (https://the-odds-api.com — free signup)
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("odds_fetcher")

_BASE = "https://api.the-odds-api.com/v4"

# API-Football league_id → The Odds API sport key
LEAGUE_SPORT_KEY: dict[int, str] = {
    39: "soccer_epl",
    140: "soccer_spain_la_liga",
    135: "soccer_italy_serie_a",
    61: "soccer_france_ligue_one",
    78: "soccer_germany_bundesliga",
    2: "soccer_uefa_champs_league",
    3: "soccer_uefa_europa_league",
    292: "soccer_korea_kleague1",
}


@dataclass
class MatchOdds:
    home_team: str = ""
    away_team: str = ""
    home_win: float = 0.0
    draw: float = 0.0
    away_win: float = 0.0
    over_2_5: float = 0.0
    under_2_5: float = 0.0
    btts_yes: float = 0.0
    btts_no: float = 0.0
    bookmaker: str = ""

    @property
    def has_odds(self) -> bool:
        return self.home_win > 0 and self.draw > 0 and self.away_win > 0

    def format_h2h(self) -> str:
        """Return formatted 1X2 odds string for display."""
        if not self.has_odds:
            return ""
        return f"홈 {self.home_win:.2f} | 무 {self.draw:.2f} | 원정 {self.away_win:.2f}"

    def format_ou(self) -> str:
        """Return formatted O/U 2.5 odds string."""
        if not self.over_2_5:
            return ""
        return f"오버2.5 {self.over_2_5:.2f} | 언더2.5 {self.under_2_5:.2f}"


def _best_odds_from_event(event: dict[str, Any]) -> MatchOdds:
    """Extract best available odds from a single Odds API event."""
    odds = MatchOdds(
        home_team=event.get("home_team", ""),
        away_team=event.get("away_team", ""),
    )

    h2h_home: list[float] = []
    h2h_draw: list[float] = []
    h2h_away: list[float] = []
    overs: list[float] = []
    unders: list[float] = []
    btts_yes: list[float] = []
    btts_no: list[float] = []

    for bookie in event.get("bookmakers", [])[:5]:
        odds.bookmaker = bookie.get("key", "")
        for market in bookie.get("markets", []):
            key = market.get("key", "")
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            if key == "h2h":
                h2h_home.append(outcomes.get(event["home_team"], 0))
                h2h_draw.append(outcomes.get("Draw", 0))
                h2h_away.append(outcomes.get(event["away_team"], 0))
            elif key == "totals":
                for o in market.get("outcomes", []):
                    if o["name"] == "Over":
                        overs.append(o["price"])
                    elif o["name"] == "Under":
                        unders.append(o["price"])
            elif key == "btts":
                btts_yes.append(outcomes.get("Yes", 0))
                btts_no.append(outcomes.get("No", 0))

    def _avg(lst: list[float]) -> float:
        valid = [x for x in lst if x > 0]
        return round(sum(valid) / len(valid), 2) if valid else 0.0

    odds.home_win = _avg(h2h_home)
    odds.draw = _avg(h2h_draw)
    odds.away_win = _avg(h2h_away)
    odds.over_2_5 = _avg(overs)
    odds.under_2_5 = _avg(unders)
    odds.btts_yes = _avg(btts_yes)
    odds.btts_no = _avg(btts_no)
    return odds


def _fuzzy_match(name: str, candidates: list[str], threshold: float = 0.7) -> str | None:
    name_lower = name.lower()
    best_ratio, best_match = 0.0, None
    for c in candidates:
        ratio = difflib.SequenceMatcher(None, name_lower, c.lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_match = ratio, c
    return best_match if best_ratio >= threshold else None


async def fetch_odds_for_league(
    league_id: int,
    hours_ahead: int = 72,
) -> list[MatchOdds]:
    """Fetch upcoming match odds for a league. Returns empty list on failure."""
    api_key = settings.odds_api_key
    if not api_key:
        return []

    sport_key = LEAGUE_SPORT_KEY.get(league_id)
    if not sport_key:
        return []

    now = datetime.now(timezone.utc)
    commence_to = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_BASE}/sports/{sport_key}/odds/",
                params={
                    "apiKey": api_key,
                    "regions": "eu",
                    "markets": "h2h,totals,btts",
                    "oddsFormat": "decimal",
                    "commenceTo": commence_to,
                },
            )
        if resp.status_code == 401:
            logger.error("The Odds API: invalid key")
            return []
        if resp.status_code == 422:
            logger.warning("The Odds API: quota exceeded")
            return []
        if resp.status_code != 200:
            logger.warning("The Odds API: HTTP %d", resp.status_code)
            return []

        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.info("Odds API OK — %s requests remaining", remaining)
        return [_best_odds_from_event(e) for e in resp.json()]

    except Exception as e:
        logger.warning("Odds API fetch failed: %s", e)
        return []


def match_odds_to_game(
    home_team: str,
    away_team: str,
    odds_list: list[MatchOdds],
) -> MatchOdds | None:
    """Fuzzy-match API-Football team names to Odds API team names."""
    all_home = [o.home_team for o in odds_list]
    matched_home = _fuzzy_match(home_team, all_home)
    if not matched_home:
        return None
    for o in odds_list:
        if o.home_team == matched_home:
            return o
    return None
