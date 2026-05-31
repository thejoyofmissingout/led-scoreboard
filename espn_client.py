"""
ESPN API client — fetches and normalizes scoreboard data for all 5 leagues.
All heavy lifting happens here so the CircuitPython board gets tiny JSON.

Live score refresh uses native MLB/NHL APIs for lower latency:
  MLB: statsapi.mlb.com  (~10-15s behind live vs ESPN's ~30-45s)
  NHL: api-web.nhle.com  (~10-15s behind live vs ESPN's ~30-45s)
  NBA/NFL/WNBA: ESPN summary endpoint (unchanged)
"""

import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

ENDPOINTS = {
    "MLB":  "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "NHL":  "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "NBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "NFL":  "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "WNBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "ATP":  "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "WTA":  "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard",
}

_TENNIS_LEAGUES = frozenset({"ATP", "WTA"})

SUMMARY_ENDPOINTS = {
    "MLB":  "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary",
    "NHL":  "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary",
    "NBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
    "NFL":  "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
    "WNBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary",
}

# Cache: (timestamp, all_games_list)
_cache = (0, [])
CACHE_TTL_LIVE = 15   # seconds when live games exist
CACHE_TTL_IDLE = 60   # seconds when no live games

# User's UTC offset for pre-game time display
UTC_OFFSET_HOURS = -4  # Eastern Daylight Time (EDT, Boston)

# Native API ID maps: ESPN game id (str) → native game id (str)
# Rebuilt on every ESPN cache refresh.
_mlb_native_ids = {}
_nhl_native_ids = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_today_str():
    """Return today's date as YYYY-MM-DD in the user's local timezone."""
    dt = datetime.now(timezone.utc) + timedelta(hours=UTC_OFFSET_HOURS)
    return dt.strftime("%Y-%m-%d")


def _fetch_league(league, url):
    """Fetch one league's scoreboard. Returns list of normalized game dicts."""
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        games = []
        for event in data.get("events", []):
            game = _normalize_event(league, event)
            if game:
                games.append(game)
        return games
    except Exception as e:
        print(f"[espn] Error fetching {league}: {e}")
        return []


def _color_distance(hex1, hex2):
    """Perceptual distance between two hex color strings."""
    try:
        c1 = int(hex1, 16)
        c2 = int(hex2, 16)
        r = ((c1 >> 16) & 0xFF) - ((c2 >> 16) & 0xFF)
        g = ((c1 >> 8)  & 0xFF) - ((c2 >> 8)  & 0xFF)
        b = (c1 & 0xFF)         - (c2 & 0xFF)
        # Weight channels by perceptual importance
        return (0.299 * r**2 + 0.587 * g**2 + 0.114 * b**2) ** 0.5
    except Exception:
        return 999


def _best_contrast_pair(ac, ac_alt, hc, hc_alt):
    """
    Pick the combination of primary/alternate colors that maximizes
    contrast between the two teams. Returns (away_color, home_color).
    """
    SIMILARITY_THRESHOLD = 60  # out of ~255 max perceptual distance

    if _color_distance(ac, hc) >= SIMILARITY_THRESHOLD:
        return ac, hc  # Primary colors are distinct enough

    # Try all combinations and pick the most contrasting
    candidates = [
        (ac,     hc_alt),
        (ac_alt, hc),
        (ac_alt, hc_alt),
    ]
    best = max(candidates, key=lambda p: _color_distance(p[0], p[1]))
    return best


_TENNIS_SLUG = {"ATP": "mens-singles", "WTA": "womens-singles"}


def _normalize_tennis_match(league, competition):
    """Map a single tennis competition → compact game dict for the board."""
    try:
        competitors = competition.get("competitors", [])
        if len(competitors) < 2:
            return None

        status_type = competition["status"]["type"]
        status_name = status_type.get("name", "")

        if status_name == "STATUS_SCHEDULED":
            live = 0
        elif status_name in ("STATUS_FINAL", "STATUS_RETIRED", "STATUS_WALKOVER"):
            live = 2
        else:
            live = 1

        try:
            p1 = next(c for c in competitors if c.get("homeAway") == "away")
            p2 = next(c for c in competitors if c.get("homeAway") == "home")
        except StopIteration:
            p1, p2 = competitors[0], competitors[1]

        def _abbr(competitor):
            ath = competitor.get("athlete", {})
            name = ath.get("displayName", "???")
            return (name.split()[-1][:3].upper() + "   ")[:3]

        def _sets_won(competitor):
            return str(sum(1 for ls in competitor.get("linescores", []) if ls.get("winner")))

        p1_score = _sets_won(p1) if live > 0 else "--"
        p2_score = _sets_won(p2) if live > 0 else "--"

        # Fixed contrasting colors per tour (players have no team colors)
        ac = "1565c0" if league == "ATP" else "c62828"  # blue / deep red
        hc = "e65100" if league == "ATP" else "6a1b9a"  # orange / purple

        period = competition["status"].get("period", 0)

        if live == 0:
            try:
                date_str = competition.get("date", "")
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                local_dt = dt + timedelta(hours=UTC_OFFSET_HOURS)
                hour = local_dt.hour
                minute = local_dt.minute
                ampm = "PM" if hour >= 12 else "AM"
                hour12 = hour % 12 or 12
                st = f"{hour12}:{minute:02d} {ampm}"
            except Exception:
                st = "UPCOMING"
        elif live == 2:
            st = "FINAL"
        else:
            # Current set number + game score within that set
            ls1 = p1.get("linescores", [])
            ls2 = p2.get("linescores", [])
            cur1 = int(ls1[-1]["value"]) if ls1 else 0
            cur2 = int(ls2[-1]["value"]) if ls2 else 0
            st = f"S{period} {cur1}-{cur2}"

        return {
            "id":   competition["id"],
            "lg":   league,
            "at":   _abbr(p1),
            "ht":   _abbr(p2),
            "as":   p1_score[:4],
            "hs":   p2_score[:4],
            "ac":   ac,
            "hc":   hc,
            "st":   st[:12],
            "live": live,
        }
    except Exception as e:
        print(f"[tennis] normalize error: {e}")
        return None


def _fetch_tennis_league(league, url):
    """
    Fetch tennis scoreboard. ESPN nests individual matches inside
    event.groupings[].competitions[], not directly in event.competitions[].
    Returns only today's singles matches (recent=True flag).
    """
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        matches = []
        for event in data.get("events", []):
            for grouping in event.get("groupings", []):
                slug = grouping.get("grouping", {}).get("slug", "")
                if slug != _TENNIS_SLUG.get(league):
                    continue
                for competition in grouping.get("competitions", []):
                    if not competition.get("recent", False):
                        continue
                    match = _normalize_tennis_match(league, competition)
                    if match:
                        matches.append(match)
        return matches
    except Exception as e:
        print(f"[espn] Error fetching {league}: {e}")
        return []


def _normalize_event(league, event):
    """Map ESPN event dict → compact game dict for the board."""
    try:
        competition = event["competitions"][0]
        competitors = competition["competitors"]

        away = next(c for c in competitors if c["homeAway"] == "away")
        home = next(c for c in competitors if c["homeAway"] == "home")

        status = event["status"]
        status_type = status["type"]
        status_name = status_type.get("name", "")

        # live: 0=scheduled, 1=in-progress, 2=final
        if status_name == "STATUS_SCHEDULED":
            live = 0
        elif status_name == "STATUS_FINAL":
            live = 2
        else:
            live = 1

        # Build status string (≤12 chars)
        st = _build_status_string(league, event, status, live)

        # Team colors — fallback to generic if missing
        away_color  = away["team"].get("color", "444444") or "444444"
        away_alt    = away["team"].get("alternateColor", away_color) or away_color
        home_color  = home["team"].get("color", "444444") or "444444"
        home_alt    = home["team"].get("alternateColor", home_color) or home_color

        # If the two primary colors are too similar, try alternate colors for contrast
        away_color, home_color = _best_contrast_pair(
            away_color, away_alt, home_color, home_alt
        )

        # Abbreviations padded/trimmed to 3 chars
        away_abbr = (away["team"].get("abbreviation", "???") + "   ")[:3]
        home_abbr = (home["team"].get("abbreviation", "???") + "   ")[:3]

        away_score = away.get("score", "--") if live > 0 else "--"
        home_score = home.get("score", "--") if live > 0 else "--"

        return {
            "id":   event["id"],
            "lg":   league[:4],
            "at":   away_abbr,
            "ht":   home_abbr,
            "as":   str(away_score)[:4],
            "hs":   str(home_score)[:4],
            "ac":   away_color[:6],
            "hc":   home_color[:6],
            "st":   st[:12],
            "live": live,
        }
    except Exception as e:
        print(f"[espn] normalize error: {e}")
        return None


def _build_status_string(league, event, status, live):
    """Build ≤12 char status string appropriate to league and game state."""
    status_type = status["type"]

    if live == 0:
        # Pre-game: show local start time
        try:
            date_str = event.get("date", "")
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            local_dt = dt + timedelta(hours=UTC_OFFSET_HOURS)
            hour = local_dt.hour
            minute = local_dt.minute
            ampm = "PM" if hour >= 12 else "AM"
            hour12 = hour % 12 or 12
            return f"{hour12}:{minute:02d} {ampm}"
        except Exception:
            return "UPCOMING"

    if live == 2:
        return "FINAL"

    # Live game — format depends on sport
    detail = status_type.get("shortDetail", "")

    if league == "MLB":
        # ESPN provides e.g. "Mid 4th", "Top 7th", "Bot 9th" — use as-is
        return detail[:12]

    # For timed sports, build "CLOCK PERIOD"
    clock = status.get("displayClock", "")
    period = status.get("period", 0)

    if league == "NHL":
        period_str = {1: "P1", 2: "P2", 3: "P3"}.get(period, f"P{period}")
        if "OT" in detail.upper() or period > 3:
            period_str = "OT" if period == 4 else "SO"
        return f"{period_str} {clock}"[:12]

    if league in ("NBA", "WNBA"):
        period_str = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}.get(period, f"OT")
        if period > 4:
            period_str = f"OT{period - 4}" if period > 5 else "OT"
        return f"{period_str} {clock}"[:12]

    if league == "NFL":
        period_str = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}.get(period, "OT")
        if period > 4:
            period_str = "OT"
        return f"{period_str} {clock}"[:12]

    return detail[:12]


# ---------------------------------------------------------------------------
# Native API enrichment — runs in parallel after each ESPN cache refresh
# ---------------------------------------------------------------------------

def _enrich_mlb_native_ids(mlb_games):
    """
    Build _mlb_native_ids: ESPN game id → MLB Stats API gamePk.
    Matched by (away_abbr, home_abbr). Normalizes the handful of abbrevs
    that differ between the MLB Stats API and ESPN.
    """
    global _mlb_native_ids
    # MLB Stats API abbrev → ESPN abbrev for teams that differ
    _norm = {"CWS": "CHW", "AZ": "ARI"}
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": _get_today_str(), "hydrate": "team"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        pk_map = {}
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                at_raw = game["teams"]["away"]["team"].get("abbreviation", "").upper()
                ht_raw = game["teams"]["home"]["team"].get("abbreviation", "").upper()
                at = _norm.get(at_raw, at_raw)
                ht = _norm.get(ht_raw, ht_raw)
                pk_map[(at, ht)] = str(game["gamePk"])
        new_map = {}
        for g in mlb_games:
            key = (g["at"].strip().upper(), g["ht"].strip().upper())
            if key in pk_map:
                new_map[g["id"]] = pk_map[key]
        _mlb_native_ids = new_map
        print(f"[mlb] mapped {len(new_map)}/{len(mlb_games)} games to native IDs")
    except Exception as e:
        print(f"[mlb] native ID lookup failed: {e}")


def _enrich_nhl_native_ids(nhl_games):
    """
    Build _nhl_native_ids: ESPN game id → NHL API game id.
    Matched by (away_abbr, home_abbr).
    """
    global _nhl_native_ids
    try:
        resp = requests.get(
            f"https://api-web.nhle.com/v1/score/{_get_today_str()}",
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        id_map = {}
        for game in data.get("games", []):
            at = game.get("awayTeam", {}).get("abbrev", "").upper()
            ht = game.get("homeTeam", {}).get("abbrev", "").upper()
            id_map[(at, ht)] = str(game["id"])
        new_map = {}
        for g in nhl_games:
            key = (g["at"].strip().upper(), g["ht"].strip().upper())
            if key in id_map:
                new_map[g["id"]] = id_map[key]
        _nhl_native_ids = new_map
        print(f"[nhl] mapped {len(new_map)}/{len(nhl_games)} games to native IDs")
    except Exception as e:
        print(f"[nhl] native ID lookup failed: {e}")


# ---------------------------------------------------------------------------
# Native API live refresh — called every 2s per selected live game
# ---------------------------------------------------------------------------

def _refresh_mlb_game(game):
    """Fetch current MLB score from statsapi.mlb.com linescore endpoint."""
    game_pk = _mlb_native_ids.get(game["id"])
    if not game_pk:
        return None
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/game/{game_pk}/linescore",
            timeout=5,
        )
        resp.raise_for_status()
        d = resp.json()
        away_runs = str(d.get("teams", {}).get("away", {}).get("runs", "--"))
        home_runs = str(d.get("teams", {}).get("home", {}).get("runs", "--"))
        inning = d.get("currentInningOrdinal", "")
        half = "Top" if d.get("inningHalf", "") == "Top" else "Bot"
        st = f"{half} {inning}"[:12] if inning else game["st"]
        if d.get("isGameOver", False):
            st = "FINAL"
        offense = d.get("offense", {})
        runners = (
            (1 if offense.get("first")  else 0) |
            (2 if offense.get("second") else 0) |
            (4 if offense.get("third")  else 0)
        )
        return {
            "as": away_runs[:4],
            "hs": home_runs[:4],
            "st": st,
            "runners": runners,
            "outs":    int(d.get("outs",    0)),
            "balls":   int(d.get("balls",   0)),
            "strikes": int(d.get("strikes", 0)),
        }
    except Exception as e:
        print(f"[mlb] linescore error {game_pk}: {e}")
        return None


def _refresh_nhl_game(game):
    """Fetch current NHL score from api-web.nhle.com boxscore endpoint."""
    game_id = _nhl_native_ids.get(game["id"])
    if not game_id:
        return None
    try:
        resp = requests.get(
            f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore",
            timeout=5,
        )
        resp.raise_for_status()
        d = resp.json()
        away_score = str(d.get("awayTeam", {}).get("score", "--"))
        home_score = str(d.get("homeTeam", {}).get("score", "--"))
        state = d.get("gameState", "")
        if state in ("FINAL", "OFF"):
            st = "FINAL"
        else:
            period = d.get("period", 0)
            clock = d.get("clock", {})
            time_left = clock.get("timeRemaining", "")
            intermission = clock.get("inIntermission", False)
            period_str = {1: "P1", 2: "P2", 3: "P3"}.get(period, "OT" if period == 4 else "SO")
            if intermission:
                st = f"INT {period_str}"[:12]
            elif time_left:
                st = f"{period_str} {time_left}"[:12]
            else:
                st = period_str
        return {"as": away_score[:4], "hs": home_score[:4], "st": st}
    except Exception as e:
        print(f"[nhl] boxscore error {game_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# ESPN summary fallback (NBA, NFL, WNBA; MLB/NHL when native lookup fails)
# ---------------------------------------------------------------------------

def _fetch_game_summary(game):
    """
    Fetch fresher score for a single live game.
    MLB/NHL: native API first, ESPN fallback.
    Everything else: ESPN summary endpoint.
    """
    league = game["lg"].strip()

    if league == "MLB":
        result = _refresh_mlb_game(game)
        if result:
            return result

    if league == "NHL":
        result = _refresh_nhl_game(game)
        if result:
            return result

    # ESPN fallback
    url = SUMMARY_ENDPOINTS.get(league)
    if not url:
        return None
    try:
        resp = requests.get(url, params={"event": game["id"]}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        comp = data["header"]["competitions"][0]
        competitors = comp["competitors"]
        away = next(c for c in competitors if c["homeAway"] == "away")
        home = next(c for c in competitors if c["homeAway"] == "home")
        status = comp["status"]
        status_type = status["type"]

        live_status = status_type.get("name", "")
        if live_status == "STATUS_FINAL":
            st = "FINAL"
        else:
            detail = status_type.get("shortDetail", "")
            if league == "MLB":
                st = detail[:12]
            else:
                clock = status.get("displayClock", "")
                period = status.get("period", 0)
                if league == "NHL":
                    period_str = {1:"P1",2:"P2",3:"P3"}.get(period, f"P{period}")
                    if period > 3: period_str = "OT" if period == 4 else "SO"
                elif league in ("NBA", "WNBA"):
                    period_str = {1:"Q1",2:"Q2",3:"Q3",4:"Q4"}.get(period, "OT")
                    if period > 4: period_str = f"OT{period-4}" if period > 5 else "OT"
                else:
                    period_str = {1:"Q1",2:"Q2",3:"Q3",4:"Q4"}.get(period, "OT")
                st = f"{period_str} {clock}"[:12]

        result = {"as": str(away.get("score", "--"))[:4], "hs": str(home.get("score", "--"))[:4], "st": st}

        if league in ("NBA", "WNBA"):
            situation = comp.get("situation") or {}
            sc = situation.get("shotClock")
            result["shot_clock"] = int(sc) if sc is not None else -1

            bonus_away = False
            bonus_home = False
            for bt in data.get("boxscore", {}).get("teams", []):
                ha = bt.get("homeAway", "")
                stats = {s.get("name"): s.get("displayValue", "0")
                         for s in bt.get("statistics", []) if s.get("name")}
                ib = str(stats.get("inBonus", "0"))
                in_bonus = ib not in ("0", "false", "False", "")
                if ha == "away":
                    bonus_away = in_bonus
                elif ha == "home":
                    bonus_home = in_bonus
            result["bonus_away"] = bonus_away
            result["bonus_home"] = bonus_home

        return result
    except Exception as e:
        print(f"[espn] summary error {game['id']}: {e}")
        return None


def refresh_live_scores(games):
    """
    For each live selected game, fetch the freshest available score.
    MLB/NHL use native APIs; others use ESPN summary. Runs in parallel.
    """
    live_games = [g for g in games if g["live"] == 1]
    if not live_games:
        return games

    updated = {g["id"]: g.copy() for g in games}

    with ThreadPoolExecutor(max_workers=len(live_games)) as executor:
        futures = {executor.submit(_fetch_game_summary, g): g["id"] for g in live_games}
        for future in as_completed(futures):
            gid = futures[future]
            result = future.result()
            if result:
                updated[gid].update(result)

    return [updated[g["id"]] for g in games]


# ---------------------------------------------------------------------------
# Main fetch — ESPN for all leagues, then enrich MLB/NHL with native IDs
# ---------------------------------------------------------------------------

def fetch_all_games(force=False):
    """
    Fetch all leagues concurrently from ESPN. Returns flat list of normalized game dicts.
    After each refresh, builds native ID maps for MLB and NHL in parallel.
    Cache TTL is 15s when live games exist, 60s otherwise.
    """
    global _cache
    ts, cached = _cache
    has_live = any(g["live"] == 1 for g in cached)
    ttl = CACHE_TTL_LIVE if has_live else CACHE_TTL_IDLE

    if not force and time.time() - ts < ttl:
        return cached

    all_games = []
    with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as executor:
        futures = {}
        for lg, url in ENDPOINTS.items():
            fn = _fetch_tennis_league if lg in _TENNIS_LEAGUES else _fetch_league
            futures[executor.submit(fn, lg, url)] = lg
        for future in as_completed(futures):
            all_games.extend(future.result())

    # Build native ID maps for MLB/NHL in parallel (best-effort; errors are non-fatal)
    mlb_games = [g for g in all_games if g["lg"].strip() == "MLB"]
    nhl_games = [g for g in all_games if g["lg"].strip() == "NHL"]
    enrich_tasks = []
    if mlb_games:
        enrich_tasks.append((_enrich_mlb_native_ids, mlb_games))
    if nhl_games:
        enrich_tasks.append((_enrich_nhl_native_ids, nhl_games))
    if enrich_tasks:
        with ThreadPoolExecutor(max_workers=len(enrich_tasks)) as executor:
            futures = [executor.submit(fn, args) for fn, args in enrich_tasks]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"[enrich] error: {e}")

    _cache = (time.time(), all_games)
    return all_games


def get_selected_games(all_games, selected_ids):
    """Filter all_games to only those in selected_ids set."""
    return [g for g in all_games if g["id"] in selected_ids]


# Quick test when run directly
if __name__ == "__main__":
    print("Fetching all leagues...")
    games = fetch_all_games(force=True)
    print(f"Found {len(games)} total games\n")
    for g in games:
        status = ["SCHED", "LIVE ", "FINAL"][g["live"]]
        native = _mlb_native_ids.get(g["id"]) or _nhl_native_ids.get(g["id"]) or "-"
        print(f"[{g['lg']:<4}] {status} {g['at']} {g['as']:>4} - {g['hs']:<4} {g['ht']}  | {g['st']:<12} | nid:{native}")
