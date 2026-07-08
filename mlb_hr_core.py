"""
MLB Home Run Candidate Model -- Core Logic
============================================
Shared by both mlb_hr_model.py (terminal) and streamlit_app.py (web).
You shouldn't need to edit this file directly -- see the other two for
usage. If you DO want to tune the scoring formulas, this is where they
live (score_form, score_matchup, score_bvp, score_park_weather).
"""

import math
import os
import re
import time
import warnings
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

from pybaseball import statcast_batter, statcast_pitcher, playerid_lookup
import pybaseball
pybaseball.cache.enable()

MLB_API = "https://statsapi.mlb.com/api/v1"

# Maps MLB Stats API's full team names to the 2-3 letter abbreviations
# RotoWire uses, so projected lineups (keyed by abbreviation) can be
# matched back to the correct game/pitcher (keyed by full name).
TEAM_ABBR = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "ATH", "Athletics": "ATH",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "San Francisco Giants": "SF", "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def load_dotenv(folder: str = None):
    """
    Tiny built-in .env loader -- no extra dependency needed. Looks for a
    .env file in `folder` (defaults to this file's folder), containing
    lines like:  OPENWEATHER_API_KEY=your_key_here
    Does nothing if the file isn't there; existing environment variables
    always take priority over anything in .env.
    """
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(folder, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


# --------------------------------------------------------------------------
# Park HR factors (Statcast park factors, 100 = neutral; convert to +/- %).
# Update periodically -- these drift year to year. Pull fresh numbers from
# https://baseballsavant.mlb.com/leaderboard/statcast-park-factors and
# paste them in here; there is no reliable scrape-friendly endpoint for this
# table (it's JS-rendered), so this is a manually-maintained dict by design.
# --------------------------------------------------------------------------
PARK_HR_FACTOR = {
    "Angel Stadium": -2, "Chase Field": 4, "Oriole Park at Camden Yards": -3,
    "Fenway Park": -6, "Wrigley Field": 6, "Guaranteed Rate Field": 4,
    "Great American Ball Park": 18, "Progressive Field": -8,
    "Coors Field": 28, "Comerica Park": -9, "Minute Maid Park": 8,
    "Kauffman Stadium": -7, "Dodger Stadium": 12, "loanDepot Park": -14,
    "American Family Field": 5, "Target Field": -3, "Citi Field": -2,
    "Yankee Stadium": 10, "Oakland Coliseum": -15, "Citizens Bank Park": 9,
    "PNC Park": -13, "Petco Park": -6, "Oracle Park": -16,
    "T-Mobile Park": -10, "Busch Stadium": -9, "Tropicana Field": -5,
    "Globe Life Field": -8, "Rogers Centre": 2, "Nationals Park": 4,
    "Sutter Health Park": 22,
}

# --------------------------------------------------------------------------
# Stadium location + orientation, used to turn OpenWeatherMap's wind
# direction into "blowing out to center" vs "blowing in from center".
# cf_bearing = compass bearing (degrees, 0=N/90=E/180=S/270=W) looking from
# home plate straight out to center field. Best-effort values, not
# surveyed -- good enough to classify out/in/cross wind.
# roof: 'open' (weather applies), 'dome' (never applies), 'retractable'
# (treated as open since roof status isn't in the free schedule payload).
# --------------------------------------------------------------------------
STADIUM_INFO = {
    "Angel Stadium": {"lat": 33.8003, "lon": -117.8827, "cf_bearing": 20, "roof": "open"},
    "Chase Field": {"lat": 33.4455, "lon": -112.0667, "cf_bearing": 355, "roof": "retractable"},
    "Oriole Park at Camden Yards": {"lat": 39.2839, "lon": -76.6218, "cf_bearing": 30, "roof": "open"},
    "Fenway Park": {"lat": 42.3467, "lon": -71.0972, "cf_bearing": 40, "roof": "open"},
    "Wrigley Field": {"lat": 41.9484, "lon": -87.6553, "cf_bearing": 30, "roof": "open"},
    "Guaranteed Rate Field": {"lat": 41.8299, "lon": -87.6338, "cf_bearing": 70, "roof": "open"},
    "Great American Ball Park": {"lat": 39.0975, "lon": -84.5061, "cf_bearing": 5, "roof": "open"},
    "Progressive Field": {"lat": 41.4962, "lon": -81.6852, "cf_bearing": 0, "roof": "open"},
    "Coors Field": {"lat": 39.7559, "lon": -104.9942, "cf_bearing": 50, "roof": "open"},
    "Comerica Park": {"lat": 42.3390, "lon": -83.0485, "cf_bearing": 75, "roof": "open"},
    "Minute Maid Park": {"lat": 29.7573, "lon": -95.3555, "cf_bearing": 60, "roof": "retractable"},
    "Daikin Park": {"lat": 29.7573, "lon": -95.3555, "cf_bearing": 60, "roof": "retractable"},
    "Kauffman Stadium": {"lat": 39.0517, "lon": -94.4803, "cf_bearing": 35, "roof": "open"},
    "Dodger Stadium": {"lat": 34.0739, "lon": -118.2400, "cf_bearing": 15, "roof": "open"},
    "loanDepot Park": {"lat": 25.7781, "lon": -80.2196, "cf_bearing": 35, "roof": "retractable"},
    "American Family Field": {"lat": 43.0280, "lon": -87.9712, "cf_bearing": 45, "roof": "retractable"},
    "Target Field": {"lat": 44.9817, "lon": -93.2776, "cf_bearing": 85, "roof": "open"},
    "Citi Field": {"lat": 40.7571, "lon": -73.8458, "cf_bearing": 30, "roof": "open"},
    "Yankee Stadium": {"lat": 40.8296, "lon": -73.9262, "cf_bearing": 75, "roof": "open"},
    "Oakland Coliseum": {"lat": 37.7516, "lon": -122.2005, "cf_bearing": 55, "roof": "open"},
    "Sutter Health Park": {"lat": 38.5802, "lon": -121.5142, "cf_bearing": 30, "roof": "open"},
    "Citizens Bank Park": {"lat": 39.9061, "lon": -75.1665, "cf_bearing": 15, "roof": "open"},
    "PNC Park": {"lat": 40.4469, "lon": -80.0057, "cf_bearing": 10, "roof": "open"},
    "Petco Park": {"lat": 32.7073, "lon": -117.1566, "cf_bearing": 5, "roof": "open"},
    "Oracle Park": {"lat": 37.7786, "lon": -122.3893, "cf_bearing": 95, "roof": "open"},
    "T-Mobile Park": {"lat": 47.5914, "lon": -122.3325, "cf_bearing": 45, "roof": "retractable"},
    "Busch Stadium": {"lat": 38.6226, "lon": -90.1928, "cf_bearing": 30, "roof": "open"},
    "Tropicana Field": {"lat": 27.7683, "lon": -82.6534, "cf_bearing": 0, "roof": "dome"},
    "Globe Life Field": {"lat": 32.7473, "lon": -97.0847, "cf_bearing": 30, "roof": "retractable"},
    "Rogers Centre": {"lat": 43.6414, "lon": -79.3894, "cf_bearing": 45, "roof": "retractable"},
    "Nationals Park": {"lat": 38.8730, "lon": -77.0074, "cf_bearing": 30, "roof": "open"},
}


def get_schedule_and_probables(target_date: str) -> pd.DataFrame:
    """Pull today's games, starting pitchers, and venue from MLB Stats API."""
    url = f"{MLB_API}/schedule"
    params = {
        "sportId": 1,
        "date": target_date,
        "hydrate": "probablePitcher,team,linescore,venue",
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    rows = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            home = g["teams"]["home"]
            away = g["teams"]["away"]
            venue = g.get("venue", {}).get("name", "Unknown")
            rows.append({
                "game_pk": g["gamePk"],
                "venue": venue,
                "home_team": home["team"]["name"],
                "away_team": away["team"]["name"],
                "home_pitcher": home.get("probablePitcher", {}).get("fullName", "TBD"),
                "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
                "away_pitcher": away.get("probablePitcher", {}).get("fullName", "TBD"),
                "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
            })
    return pd.DataFrame(rows)


def get_probable_lineup(game_pk: int, team_side: str) -> list:
    """
    Pull confirmed (or projected) batting order for a team in a game.
    team_side is 'home' or 'away'. Returns list of (player_id, name) tuples.
    Empty list if the lineup isn't posted yet (usually ~1-3 hrs pre-game).
    """
    url = f"{MLB_API}/game/{game_pk}/boxscore"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        team_data = data.get("teams", {}).get(team_side, {})
        order = team_data.get("battingOrder", [])
        players = team_data.get("players", {})
        lineup = []
        for pid in order:
            key = f"ID{pid}"
            if key in players:
                lineup.append((pid, players[key]["person"]["fullName"]))
        return lineup
    except Exception:
        return []


def get_pitcher_hand(pitcher_id: int) -> str:
    if not pitcher_id:
        return "R"
    url = f"{MLB_API}/people/{pitcher_id}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()["people"][0]["pitchHand"]["code"]
    except Exception:
        return "R"


def get_batter_hand(batter_id: int) -> str:
    url = f"{MLB_API}/people/{batter_id}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()["people"][0]["batSide"]["code"]
    except Exception:
        return "R"


_player_id_cache = {}


def resolve_player_id(full_name: str) -> int:
    """
    Resolve a player's full name (e.g. 'George Springer') to their MLBAM
    player ID using pybaseball's Chadwick Bureau register -- needed
    because RotoWire's projected lineups give us names, not MLB IDs, and
    every Statcast lookup in this file needs an MLB ID.
    Caches within a run since the same players show up across games.
    Can fail to resolve on suffixes (Jr./II), accented characters, or
    genuinely ambiguous shared names -- returns None rather than guessing
    wrong, and that batter just gets skipped for that run.
    """
    if full_name in _player_id_cache:
        return _player_id_cache[full_name]

    parts = full_name.strip().split()
    if len(parts) < 2:
        _player_id_cache[full_name] = None
        return None
    first, last = parts[0], parts[-1]

    try:
        result = playerid_lookup(last, first)
    except Exception:
        _player_id_cache[full_name] = None
        return None

    if result is None or result.empty:
        _player_id_cache[full_name] = None
        return None

    if len(result) > 1 and "mlb_played_last" in result.columns:
        result = result.sort_values("mlb_played_last", ascending=False)

    mlbam = result.iloc[0].get("key_mlbam")
    pid = int(mlbam) if pd.notna(mlbam) else None
    _player_id_cache[full_name] = pid
    return pid


def get_rotowire_projected_lineups(target_date: str = None) -> list:
    """
    Scrapes RotoWire's public daily lineups page for PROJECTED batting
    orders -- available much earlier in the day than MLB's official
    confirmed lineup (which usually only posts 1-3 hrs pre-game). This is
    a best-effort scrape of a public page's HTML structure, not an
    official API. RotoWire only exposes 'today' and 'tomorrow' this way
    (no arbitrary past/future dates) -- returns [] for anything else.

    IMPORTANT: this was written against RotoWire's typical markup
    conventions but has not been run against the live page (this
    environment can't reach rotowire.com to test). If this returns an
    empty list when you know there are games today, that's the signal
    the CSS selectors below need adjusting to match RotoWire's actual
    current markup -- not that something deeper is broken. Easiest fix:
    save r.text to a local .html file, open it, find the real class
    names around a player's name, and swap them in below.

    Returns a list of dicts, one per game:
      {'away_team': 'TOR', 'home_team': 'SF',
       'away_pitcher': 'Dylan Cease', 'home_pitcher': 'Logan Webb',
       'away_lineup': [{'name': 'George Springer', 'pos': 'DH', 'hand': 'R'}, ...],
       'home_lineup': [...]}
    Team abbreviations match TEAM_ABBR above.
    """
    url = "https://www.rotowire.com/baseball/daily-lineups.php"
    today_str = date.today().strftime("%Y-%m-%d")
    if target_date and target_date != today_str:
        tomorrow_str = (date.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if target_date == tomorrow_str:
            url += "?date=tomorrow"
        else:
            return []

    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"  Couldn't reach RotoWire: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    games = []

    boxes = soup.select("div.lineup.is-mlb") or soup.select("div.lineup")
    for box in boxes:
        try:
            abbrs = box.select(".lineup__abbr")
            if len(abbrs) < 2:
                continue
            away_abbr = abbrs[0].get_text(strip=True)
            home_abbr = abbrs[1].get_text(strip=True)

            pitcher_els = box.select(".lineup__player-highlight-name a") or \
                box.select(".lineup__player-highlight a")
            away_pitcher = pitcher_els[0].get_text(strip=True) if len(pitcher_els) > 0 else None
            home_pitcher = pitcher_els[1].get_text(strip=True) if len(pitcher_els) > 1 else None

            lists = box.select("ul.lineup__list")

            def parse_lineup(ul):
                out = []
                if not ul:
                    return out
                for li in ul.select("li.lineup__player"):
                    name_el = li.select_one("a")
                    if not name_el:
                        continue
                    name = name_el.get("title") or name_el.get_text(strip=True)
                    pos_el = li.select_one(".lineup__pos")
                    pos = pos_el.get_text(strip=True) if pos_el else None
                    full_text = li.get_text(" ", strip=True)
                    hand_match = re.search(r"\b([LRS])\b\s*$", full_text)
                    hand = hand_match.group(1) if hand_match else None
                    out.append({"name": name, "pos": pos, "hand": hand})
                return out

            away_list = parse_lineup(lists[0]) if len(lists) >= 1 else []
            home_list = parse_lineup(lists[1]) if len(lists) >= 2 else []

            games.append({
                "away_team": away_abbr,
                "home_team": home_abbr,
                "away_pitcher": away_pitcher,
                "home_pitcher": home_pitcher,
                "away_lineup": away_list,
                "home_lineup": home_list,
            })
        except Exception:
            continue

    return games


_batter_df_cache = {}
_pitcher_df_cache = {}

# Raw Statcast pulls return 90+ columns per pitch (pitch type, spin rate,
# release point, etc.) -- this model only ever touches these. Trimming
# immediately after each fetch, before caching, cuts memory per dataframe
# by roughly an order of magnitude, which matters a lot when holding many
# batters'/pitchers' data at once (this was the main driver of the
# out-of-memory crash on Streamlit Cloud's free tier).
_BATTER_COLS = ["game_date", "events", "launch_speed", "launch_angle", "p_throws", "pitcher"]
_PITCHER_COLS = ["events", "launch_speed", "launch_angle", "stand"]


def _trim_and_shrink(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """Keep only needed columns and downcast dtypes to reduce memory use."""
    if df is None or df.empty:
        return df
    keep = [c for c in cols if c in df.columns]
    df = df[keep].copy()
    for c in ("events", "p_throws", "stand"):
        if c in df.columns:
            df[c] = df[c].astype("category")
    for c in ("launch_speed", "launch_angle"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    if "pitcher" in df.columns:
        df["pitcher"] = pd.to_numeric(df["pitcher"], errors="coerce").astype("Int32")
    return df


def _get_batter_statcast(batter_id: int) -> pd.DataFrame:
    """
    Pulls this batter's full Statcast pitch-level history ONCE (2015 to
    today) and caches it in memory for the rest of this run. score_form,
    score_matchup, and score_bvp all slice from this single cached pull
    instead of each doing their own separate network fetch. This is the
    single biggest speed fix -- previously each batter triggered 3
    separate downloads of increasingly-overlapping date ranges; now it's
    1 download, filtered locally in pandas (fast, no network) 3 ways.
    Trimmed to only the columns actually used (see _BATTER_COLS) to keep
    memory reasonable across an entire slate's worth of batters.
    """
    if batter_id in _batter_df_cache:
        return _batter_df_cache[batter_id]
    try:
        df = statcast_batter("2015-01-01", date.today().strftime("%Y-%m-%d"), batter_id)
    except Exception:
        df = pd.DataFrame()
    if df is not None and not df.empty and "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"])
    df = _trim_and_shrink(df, _BATTER_COLS)
    _batter_df_cache[batter_id] = df
    return df


def _get_pitcher_statcast(pitcher_id: int) -> pd.DataFrame:
    """
    Same idea for pitchers, cached per pitcher per run. This is the other
    big fix: every batter facing the same starter was triggering its own
    fresh season-long pull of that pitcher's data -- 9+ redundant
    downloads of identical data per game. Now it's 1 per pitcher, reused
    across every batter who faces them. Also trimmed to only the columns
    actually used (see _PITCHER_COLS).
    """
    if pitcher_id in _pitcher_df_cache:
        return _pitcher_df_cache[pitcher_id]
    season_start = f"{date.today().year}-03-01"
    try:
        df = statcast_pitcher(season_start, date.today().strftime("%Y-%m-%d"), pitcher_id)
    except Exception:
        df = pd.DataFrame()
    df = _trim_and_shrink(df, _PITCHER_COLS)
    _pitcher_df_cache[pitcher_id] = df
    return df


def _release_batter_cache(batter_id: int):
    """Evict a batter's cached data once we're fully done scoring them --
    unlike pitchers (shared across ~9 batters per game), each batter is
    normally only scored once per run, so there's no reuse benefit to
    keeping their data around afterward. This bounds peak memory to
    roughly 'one batter + all pitchers seen so far' instead of 'every
    batter + every pitcher, all at once' by the end of a full slate."""
    _batter_df_cache.pop(batter_id, None)


def _release_pitcher_cache(pitcher_id: int):
    """Evict a pitcher's cached data once every batter facing them this
    run has been scored."""
    _pitcher_df_cache.pop(pitcher_id, None)


def score_form(batter_id: int, days: int = 14) -> tuple:
    """FM score: recent HR-quality contact (Statcast 'tanks') + HR recency."""
    df = _get_batter_statcast(batter_id)
    if df is None or df.empty:
        return 50, "no statcast data"

    end = date.today()
    recent = df[df["game_date"] >= pd.Timestamp(end) - pd.Timedelta(days=days)]

    batted = recent.dropna(subset=["launch_speed", "launch_angle"])
    tanks = batted[(batted["launch_speed"] >= 102) &
                    (batted["launch_angle"].between(20, 38))]

    hr_events = df[df["events"] == "home_run"].sort_values("game_date", ascending=False)
    days_since_hr = (pd.Timestamp(end) - hr_events["game_date"].iloc[0]).days if not hr_events.empty else 999

    n_tanks = len(tanks)
    score = 50 + (n_tanks * 4)
    if days_since_hr <= 3:
        score += 10
    elif days_since_hr > 21:
        score -= 10
    score = max(0, min(100, score))
    note = f"{n_tanks} tanks/{days}d, last HR {days_since_hr}d ago"
    return round(score), note


def _is_barrel(ev: pd.Series, la: pd.Series) -> pd.Series:
    """
    Approximates Statcast's official 'barrel' classification. It is NOT a
    fixed exit-velo/launch-angle box -- the qualifying launch-angle window
    widens as exit velocity climbs (narrow, ~26-30 degrees, right at the
    98 mph minimum; a full ~8-50 degree window by 116+ mph). Using a fixed
    narrow window like the old version of this function undercounts
    barrels, especially on the hardest-hit balls -- this linear widening
    approximation tracks Savant's real lookup table much more closely,
    though it's still an approximation, not a pixel-perfect match to
    Savant's own published barrel counts for a given player.
    """
    ev_capped = ev.clip(upper=116)
    widen_frac = (ev_capped - 98).clip(lower=0) / (116 - 98)
    lower_la = 26 - widen_frac * (26 - 8)
    upper_la = 30 + widen_frac * (50 - 30)
    return (ev >= 98) & (la >= lower_la) & (la <= upper_la)


def score_matchup(batter_id: int, pitcher_id: int, batter_hand: str, pitcher_hand: str) -> tuple:
    """MU score: batter barrel rate vs this hand blended with pitcher leak."""
    season_start = pd.Timestamp(f"{date.today().year}-03-01")

    bdf_full = _get_batter_statcast(batter_id)
    bdf = bdf_full[bdf_full["game_date"] >= season_start] if not bdf_full.empty else bdf_full

    pdf = _get_pitcher_statcast(pitcher_id)

    batter_barrel_pct = 8.0
    if not bdf.empty and "p_throws" in bdf.columns:
        vs_hand = bdf[bdf["p_throws"] == pitcher_hand]
        batted = vs_hand.dropna(subset=["launch_speed", "launch_angle"])
        if len(batted) >= 15:
            barrels = batted[_is_barrel(batted["launch_speed"], batted["launch_angle"])]
            batter_barrel_pct = 100 * len(barrels) / len(batted)

    pitcher_hr9_to_hand = 1.2
    pitcher_barrel_allowed = 7.0
    if not pdf.empty and "stand" in pdf.columns:
        vs_side = pdf[pdf["stand"] == batter_hand]
        batted = vs_side.dropna(subset=["launch_speed", "launch_angle"])
        if len(batted) >= 15:
            barrels = batted[_is_barrel(batted["launch_speed"], batted["launch_angle"])]
            pitcher_barrel_allowed = 100 * len(barrels) / len(batted)
            hrs = len(vs_side[vs_side["events"] == "home_run"])
            # statcast_pitcher() returns one row PER PITCH, not per plate
            # appearance -- counting rows here (as the old code did) counts
            # roughly 4 pitches per batter faced, wildly overstating innings
            # pitched and understating HR/9 by close to that same 4x. Count
            # actual plate appearances instead: "events" is only populated
            # on the final pitch of each PA.
            pa_faced = vs_side["events"].notna().sum()
            ip_est = max(pa_faced / 4.3, 1)  # ~4.3 batters faced per inning, MLB-average estimate
            pitcher_hr9_to_hand = (hrs / ip_est) * 9

    score = 50
    score += (batter_barrel_pct - 8) * 2
    score += (pitcher_hr9_to_hand - 1.2) * 10
    score += (pitcher_barrel_allowed - 7) * 1.5
    score = max(0, min(100, score))
    note = (f"batter BRL {batter_barrel_pct:.1f}% vs {pitcher_hand}HP, "
            f"pitcher {pitcher_hr9_to_hand:.2f} HR/9 & {pitcher_barrel_allowed:.1f}% "
            f"BRL allowed to {batter_hand}HB")
    return round(score), note


def score_bvp(batter_id: int, pitcher_id: int) -> tuple:
    """
    BvP score: this batter's Statcast-era history vs this exact pitcher.
    Every plate appearance is tracked, no minimum sample size -- 0 PA is
    reported explicitly ("0 PA - no history") rather than hidden as N/A.
    Small samples are still pulled gently toward neutral (50) rather than
    swinging on 1-2 at-bats -- that's a statistical judgment call about
    how much to trust a tiny sample, not a decision to exclude anything.
    """
    df = _get_batter_statcast(batter_id)

    if df is None or df.empty or "pitcher" not in df.columns:
        return 50, "0 PA - no Statcast data available"

    vs_pitcher = df[df["pitcher"] == pitcher_id]
    pa = vs_pitcher["events"].notna().sum()

    if pa == 0:
        return 50, "0 PA - no history vs this pitcher"

    hrs = len(vs_pitcher[vs_pitcher["events"] == "home_run"])
    hard_hit = vs_pitcher.dropna(subset=["launch_speed"])
    hard_hit_pct = 100 * (hard_hit["launch_speed"] >= 95).mean() if not hard_hit.empty else 0

    weight = min(1.0, pa / 25)  # full weight by n=25 PA, regressed toward 50 below that
    raw = 50 + (hrs * 12) + (hard_hit_pct - 35) * 0.4
    score = 50 + (raw - 50) * weight
    score = max(0, min(100, score))
    return round(score), f"n={pa} PA, {hrs} HR, {hard_hit_pct:.0f}% hard-hit"


def get_weather(venue: str, owm_key: str = None) -> tuple:
    """Live wind/temp/humidity from OpenWeatherMap, translated to +/- score."""
    if not owm_key:
        return 0, "no OpenWeatherMap key set"

    info = STADIUM_INFO.get(venue)
    if not info:
        return 0, f"no stadium info for '{venue}'"

    if info["roof"] == "dome":
        return 0, "domed roof, weather n/a"

    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": info["lat"], "lon": info["lon"], "appid": owm_key, "units": "imperial"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return 0, f"lookup failed ({e})"

    wind_mph = data.get("wind", {}).get("speed", 0)
    wind_from_deg = data.get("wind", {}).get("deg", 0)
    temp_f = data.get("main", {}).get("temp", 70)
    humidity = data.get("main", {}).get("humidity", 50)

    wind_to_deg = (wind_from_deg + 180) % 360
    angle_diff = abs(wind_to_deg - info["cf_bearing"])
    angle_diff = min(angle_diff, 360 - angle_diff)

    out_component = wind_mph * math.cos(math.radians(angle_diff))

    wind_adj = out_component * 1.2
    temp_adj = max(-4, min(4, (temp_f - 70) / 10))
    humidity_adj = max(-2, min(2, (humidity - 50) / 25))

    total = wind_adj + temp_adj + humidity_adj
    total = max(-15, min(15, total))

    direction = "out" if out_component > 2 else "in" if out_component < -2 else "cross"
    note = f"wind {wind_mph:.0f}mph {direction}, {temp_f:.0f}F, {humidity:.0f}% hum"
    return round(total), note


def score_park_weather(venue: str, owm_key: str = None) -> tuple:
    park_factor = PARK_HR_FACTOR.get(venue, 0)
    weather_adj, weather_note = get_weather(venue, owm_key)
    score = 50 + park_factor + weather_adj
    score = max(0, min(100, score))
    note = f"park {park_factor:+d}%, weather {weather_adj:+d} ({weather_note})"
    return round(score), note


# --------------------------------------------------------------------------
# Default weights for the combined Total score. These are a starting point,
# not a law of nature -- adjust freely (build_candidates takes a `weights`
# override, and the Streamlit app has live sliders for this). Reasoning
# behind the defaults:
#   MU 35%  - most directly predictive: an actual pitcher weakness meeting
#             an actual batter strength, closest thing to a mechanism here.
#   FM 30%  - recent barrel-quality contact is a strong near-term signal.
#   PW 20%  - real effect, but more a multiplier on opportunity than a
#             standalone driver -- matters most at the extremes.
#   BvP 15% - real when the sample's decent, but even lifetime history vs
#             one specific pitcher is often single-digit PAs -- weighted
#             lowest because it's usually the least statistically reliable
#             of the four.
# Must sum to 1.0.
# --------------------------------------------------------------------------
SCORE_WEIGHTS = {"PW": 0.20, "MU": 0.35, "FM": 0.30, "BvP": 0.15}


def build_candidates(target_date: str, owm_key: str = None, progress_callback=None,
                      weights: dict = None) -> pd.DataFrame:
    """
    The main pipeline: pull today's slate, score every batter on the 4
    sub-scores, return a ranked DataFrame with an added 'Total' column --
    a weighted blend of PW/MU/FM/BvP (see SCORE_WEIGHTS above for the
    default weights and reasoning). Pass a custom `weights` dict (same
    keys: PW, MU, FM, BvP, must sum to 1.0) to override. The sub-scores
    are still all shown individually too -- Total is a convenience
    ranking on top, not a replacement for looking at the 4 separately.

    Lineup source per game is 'confirmed' (MLB's official posted lineup,
    usually available ~1-3 hrs pre-game) when it exists, or 'projected'
    (RotoWire's early-day expected lineup) as a fallback so you can run
    this any time, well before official lineups post. Each result row
    says which one it came from -- projected lineups are a real person's
    best guess, not official, so treat those rows with a bit more
    caution, especially platoon-prone spots.

    progress_callback, if given, is called as progress_callback(message)
    with a short status string for each step -- used by the Streamlit app
    to show a live progress log. Ignored (just skipped) if not provided.
    """
    weights = weights or SCORE_WEIGHTS

    def report(msg):
        if progress_callback:
            progress_callback(msg)

    report(f"Pulling schedule for {target_date}...")
    games = get_schedule_and_probables(target_date)
    if games.empty:
        report("No games found for that date.")
        return pd.DataFrame()

    report("Pulling RotoWire projected lineups as a fallback for unposted games...")
    projected = get_rotowire_projected_lineups(target_date)
    projected_by_team = {}
    for g in projected:
        projected_by_team[g["away_team"]] = g
        projected_by_team[g["home_team"]] = g

    report(f"Found {len(games)} games. Building candidate pool...")
    results = []

    for _, g in games.iterrows():
        pw_score, pw_note = score_park_weather(g["venue"], owm_key)

        for side, opp_pitcher_id in [("home", g["away_pitcher_id"]),
                                      ("away", g["home_pitcher_id"])]:
            team_name = g["home_team"] if side == "home" else g["away_team"]
            pitcher_name = g["away_pitcher"] if side == "home" else g["home_pitcher"]
            if not opp_pitcher_id:
                continue

            pitcher_hand = get_pitcher_hand(opp_pitcher_id)

            lineup_source = "confirmed"
            lineup = get_probable_lineup(g["game_pk"], side)

            if not lineup:
                # Confirmed lineup not posted yet -- fall back to RotoWire's
                # projected lineup for this team, resolving names to MLB IDs.
                team_abbr = TEAM_ABBR.get(team_name)
                rw_game = projected_by_team.get(team_abbr)
                if rw_game:
                    rw_lineup = (rw_game["home_lineup"] if rw_game["home_team"] == team_abbr
                                 else rw_game["away_lineup"])
                    lineup = []
                    for entry in rw_lineup:
                        pid = resolve_player_id(entry["name"])
                        if pid:
                            lineup.append((pid, entry["name"]))
                    lineup_source = "projected"

            if not lineup:
                report(f"{team_name}: no confirmed or projected lineup found, skipping")
                continue

            report(f"{team_name}: using {lineup_source} lineup ({len(lineup)} batters)")

            for batter_id, batter_name in lineup:
                batter_hand = get_batter_hand(batter_id)
                if batter_hand == "S":
                    batter_hand = "R" if pitcher_hand == "L" else "L"

                report(f"Scoring {batter_name} vs {pitcher_name}...")
                mu_score, mu_note = score_matchup(batter_id, opp_pitcher_id, batter_hand, pitcher_hand)
                fm_score, fm_note = score_form(batter_id)
                bvp_score, bvp_note = score_bvp(batter_id, opp_pitcher_id)
                time.sleep(0.2)  # light politeness pause; much less needed now that
                                  # batter/pitcher data is cached and fetched once each

                total_score = (
                    pw_score * weights["PW"] + mu_score * weights["MU"] +
                    fm_score * weights["FM"] + bvp_score * weights["BvP"]
                )

                results.append({
                    "batter": batter_name,
                    "team": team_name,
                    "pitcher": pitcher_name,
                    "pitcher_hand": pitcher_hand,
                    "venue": g["venue"],
                    "lineup_source": lineup_source,
                    "Total": round(total_score, 1),
                    "PW": pw_score,
                    "PW_note": pw_note,
                    "MU": mu_score,
                    "MU_note": mu_note,
                    "FM": fm_score,
                    "FM_note": fm_note,
                    "BvP": bvp_score,
                    "BvP_note": bvp_note,
                })

                # Free this batter's data now -- unlike pitchers, each batter
                # is normally only used once per run, so there's no reuse
                # benefit to keeping it cached. This keeps peak memory from
                # growing across an entire slate (the actual cause of the
                # out-of-memory crash on Streamlit Cloud's free tier).
                _release_batter_cache(batter_id)

            # Done with every batter facing this pitcher for this game --
            # safe to free their cached data too.
            _release_pitcher_cache(opp_pitcher_id)

    if not results:
        report("No candidates scored -- no confirmed or projected lineups available yet.")
        return pd.DataFrame()

    out = pd.DataFrame(results).sort_values("Total", ascending=False).reset_index(drop=True)
    report(f"Done -- scored {len(out)} batters.")
    return out
