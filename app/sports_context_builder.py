"""
Sports Context Builder: builds verified real-data blocks for AI prompt injection.

All functions operate on data already fetched from Football-Data.org.
No fabrication — if data is absent, section is omitted.
"""
from __future__ import annotations

from app.sports_scraper import Match, TeamStanding


def _find_standing(team_name: str, standings: list[TeamStanding]) -> TeamStanding | None:
    """Fuzzy match team name against standings list."""
    name_lower = team_name.lower()
    for s in standings:
        s_lower = s.team_name.lower()
        if name_lower in s_lower or s_lower in name_lower:
            return s
        # Match on first word (e.g. "Chelsea" in "Chelsea FC")
        if name_lower.split()[0] in s_lower or s_lower.split()[0] in name_lower:
            return s
    # Second pass: check if any word in team_name matches any word in standings name
    name_words = set(w for w in name_lower.split() if len(w) > 3)
    for s in standings:
        s_words = set(w for w in s.team_name.lower().split() if len(w) > 3)
        if name_words & s_words:
            return s
    return None


def _compute_form(team_name: str, results: list[Match], n: int = 5) -> str:
    """Compute form string (e.g. 'WWDLW') from recent completed matches."""
    form_chars: list[str] = []
    name_lower = team_name.lower()
    for m in reversed(results):  # most recent first
        if m.home_score is None or m.away_score is None:
            continue
        h_lower = m.home_team.lower()
        a_lower = m.away_team.lower()
        is_home = name_lower in h_lower or h_lower in name_lower or name_lower.split()[0] in h_lower
        is_away = name_lower in a_lower or a_lower in name_lower or name_lower.split()[0] in a_lower
        if not (is_home or is_away):
            continue
        if is_home:
            ch = "W" if m.home_score > m.away_score else ("D" if m.home_score == m.away_score else "L")
        else:
            ch = "W" if m.away_score > m.home_score else ("D" if m.away_score == m.home_score else "L")
        form_chars.append(ch)
        if len(form_chars) >= n:
            break
    return "".join(form_chars)


def _filter_team_results(team_name: str, results: list[Match]) -> list[str]:
    """Format recent results for a specific team from match history."""
    lines: list[str] = []
    name_lower = team_name.lower()
    for m in reversed(results):  # most recent first
        if m.home_score is None:
            continue
        h_lower = m.home_team.lower()
        a_lower = m.away_team.lower()
        is_home = name_lower in h_lower or h_lower in name_lower
        is_away = name_lower in a_lower or a_lower in name_lower
        if not (is_home or is_away):
            continue
        if is_home:
            res = "승" if m.home_score > m.away_score else ("무" if m.home_score == m.away_score else "패")
            lines.append(f"  홈 vs {m.away_team}: {m.home_score}-{m.away_score} [{res}]")
        else:
            res = "승" if m.away_score > m.home_score else ("무" if m.away_score == m.home_score else "패")
            lines.append(f"  원정 vs {m.home_team}: {m.away_score}-{m.home_score} [{res}]")
        if len(lines) >= 3:
            break
    return lines


def _standing_lines(label: str, st: TeamStanding, results: list[Match] | None = None) -> list[str]:
    """Format one team's standing block."""
    lines = [
        f"[{label} 현재 시즌 성적]",
        f"  순위: {st.rank}위 | 승점: {st.points}pts",
        f"  {st.played}경기 {st.wins}승 {st.draws}무 {st.losses}패",
        f"  득실차: {st.goal_difference:+d} (득점 {st.goals_for} / 실점 {st.goals_against})",
    ]
    form = st.form
    if not form and results:
        form = _compute_form(st.team_name, results)
    if form:
        form_kr = form.replace("W", "✅").replace("D", "🟡").replace("L", "❌")
        lines.append(f"  최근 5경기 폼: {form_kr}  ({form})")
    return lines


def build_real_match_context(
    match: Match,
    all_results: list[Match],
    standings: list[TeamStanding],
    scorers: list[dict] | None = None,
) -> str:
    """Build verified data block for AI prompt injection."""
    from app.logging_config import get_logger
    logger = get_logger("sports_context_builder")

    lines: list[str] = ["=== 검증된 실제 데이터 (이 데이터만 사용하세요) ===", ""]

    home_st = _find_standing(match.home_team, standings)
    away_st = _find_standing(match.away_team, standings)

    if home_st:
        lines.extend(_standing_lines(match.home_team, home_st, all_results))
    else:
        logger.warning("Standing not found for home team: %s (standings: %d entries)", match.home_team, len(standings))
        lines.append(f"[{match.home_team}] 순위 데이터 없음")
    lines.append("")

    if away_st:
        lines.extend(_standing_lines(match.away_team, away_st, all_results))
    else:
        logger.warning("Standing not found for away team: %s (standings: %d entries)", match.away_team, len(standings))
        lines.append(f"[{match.away_team}] 순위 데이터 없음")
    lines.append("")

    home_recent = _filter_team_results(match.home_team, all_results)
    away_recent = _filter_team_results(match.away_team, all_results)

    if home_recent:
        lines.append(f"[{match.home_team} 최근 경기 결과]")
        lines.extend(home_recent)
        lines.append("")
    if away_recent:
        lines.append(f"[{match.away_team} 최근 경기 결과]")
        lines.extend(away_recent)
        lines.append("")

    if scorers:
        lines.append("[리그 득점 선두]")
        for s in scorers[:3]:
            lines.append(f"  {s['name']} ({s['team']}): {s['goals']}골")
        lines.append("")

    return "\n".join(lines)
