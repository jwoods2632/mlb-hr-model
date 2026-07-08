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
import time
import warnings
from datetime import date

import pandas as pd
import requests

warnings.filterwarnings("ignore")

from pybaseball import statcast_batter, statcast_pitcher
import pybaseball
pybaseball.cache.enable()

MLB_API = "https://statsapi.mlb.com/api/v1"


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


def score_form(batter_id: int, days: int = 14) -> tuple:
    """FM score: recent HR-quality contact (Statcast 'tanks') + HR recency."""
    end = date.today()
    start = end - pd.Timedelta(days=days + 30)
    try:
        df = statcast_batter(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), batter_id)
    except Exception:
        return 50, "no statcast data"

    if df is None or df.empty:
        return 50, "no statcast data"

    df["game_date"] = pd.to_datetime(df["game_date"])
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


def score_matchup(batter_id: int, pitcher_id: int, batter_hand: str, pitcher_hand: str) -> tuple:
    """MU score: batter barrel rate vs this hand blended with pitcher leak."""
    season_start = f"{date.today().year}-03-01"
    today_str = date.today().strftime("%Y-%m-%d")

    try:
        bdf = statcast_batter(season_start, today_str, batter_id)
    except Exception:
        bdf = pd.DataFrame()

    try:
        pdf = statcast_pitcher(season_start, today_str, pitcher_id)
    except Exception:
        pdf = pd.DataFrame()

    batter_barrel_pct = 8.0
    if not bdf.empty and "p_throws" in bdf.columns:
        vs_hand = bdf[bdf["p_throws"] == pitcher_hand]
        batted = vs_hand.dropna(subset=["launch_speed", "launch_angle"])
        if len(batted) >= 15:
            barrels = batted[(batted["launch_speed"] >= 98) &
                              (batted["launch_angle"].between(26, 30))]
            batter_barrel_pct = 100 * len(barrels) / len(batted)

    pitcher_hr9_to_hand = 1.2
    pitcher_barrel_allowed = 7.0
    if not pdf.empty and "stand" in pdf.columns:
        vs_side = pdf[pdf["stand"] == batter_hand]
        batted = vs_side.dropna(subset=["launch_speed", "launch_angle"])
        if len(batted) >= 15:
            barrels = batted[(batted["launch_speed"] >= 98) &
                              (batted["launch_angle"].between(26, 30))]
            pitcher_barrel_allowed = 100 * len(barrels) / len(batted)
            hrs = len(vs_side[vs_side["events"] == "home_run"])
            outs_faced = len(vs_side)
            ip_est = max(outs_faced / 4.3, 1)
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
    """BvP score: this batter's Statcast-era history vs this exact pitcher."""
    try:
        df = statcast_batter("2015-01-01", date.today().strftime("%Y-%m-%d"), batter_id)
    except Exception:
        return None, "no data"

    if df.empty or "pitcher" not in df.columns:
        return None, "no data"

    vs_pitcher = df[df["pitcher"] == pitcher_id]
    pa = vs_pitcher["events"].notna().sum()
    if pa < 8:
        return None, f"sample too small (n={pa})"

    hrs = len(vs_pitcher[vs_pitcher["events"] == "home_run"])
    hard_hit = vs_pitcher.dropna(subset=["launch_speed"])
    hard_hit_pct = 100 * (hard_hit["launch_speed"] >= 95).mean() if not hard_hit.empty else 0

    weight = min(1.0, pa / 25)
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


def build_candidates(target_date: str, owm_key: str = None, progress_callback=None) -> pd.DataFrame:
    """
    The main pipeline: pull today's slate, score every batter in every
    confirmed lineup on the 4 sub-scores, return a ranked DataFrame.

    progress_callback, if given, is called as progress_callback(message)
    with a short status string for each step -- used by the Streamlit app
    to show a live progress log. Ignored (just skipped) if not provided.
    """
    def report(msg):
        if progress_callback:
            progress_callback(msg)

    report(f"Pulling schedule for {target_date}...")
    games = get_schedule_and_probables(target_date)
    if games.empty:
        report("No games found for that date.")
        return pd.DataFrame()

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
            lineup = get_probable_lineup(g["game_pk"], side)
            if not lineup:
                report(f"{team_name}: lineup not posted yet, skipping")
                continue

            for batter_id, batter_name in lineup:
                batter_hand = get_batter_hand(batter_id)
                if batter_hand == "S":
                    batter_hand = "R" if pitcher_hand == "L" else "L"

                report(f"Scoring {batter_name} vs {pitcher_name}...")
                mu_score, mu_note = score_matchup(batter_id, opp_pitcher_id, batter_hand, pitcher_hand)
                fm_score, fm_note = score_form(batter_id)
                bvp_score, bvp_note = score_bvp(batter_id, opp_pitcher_id)
                time.sleep(0.5)  # be polite to Savant's underlying endpoints

                results.append({
                    "batter": batter_name,
                    "team": team_name,
                    "pitcher": pitcher_name,
                    "pitcher_hand": pitcher_hand,
                    "venue": g["venue"],
                    "PW": pw_score,
                    "PW_note": pw_note,
                    "MU": mu_score,
                    "MU_note": mu_note,
                    "FM": fm_score,
                    "FM_note": fm_note,
                    "BvP": bvp_score if bvp_score is not None else "N/A",
                    "BvP_note": bvp_note,
                })

    if not results:
        report("No candidates scored -- lineups likely not posted yet.")
        return pd.DataFrame()

    out = pd.DataFrame(results).sort_values("MU", ascending=False).reset_index(drop=True)
    report(f"Done -- scored {len(out)} batters.")
    return out
