"""
MLB Home Run Candidate Model -- Visual Report Generator
==========================================================
Turns the results (from build_candidates() or a saved CSV) into a
self-contained HTML report: one section per game, players ranked by
Total within each, with a compact 4-segment signal bar (PW/MU/FM/BvP)
per player instead of a wall of numbers.

USAGE (standalone, from an existing CSV)
------------------------------------------
    python mlb_hr_report.py hr_candidates_2026-07-08.csv

This produces hr_report_2026-07-08.html in the same folder and opens it
in your default browser automatically.

The terminal model (mlb_hr_model.py) also calls this automatically after
every run, so normally you won't need to run this by hand at all -- it's
here mainly for regenerating the visual from a CSV you already have
(e.g. after manually editing it) without re-pulling any data.
"""

import sys
import webbrowser
from datetime import date
from pathlib import Path

import pandas as pd

# Kept in sync with SCORE_WEIGHTS in mlb_hr_core.py. Duplicated here (rather
# than imported) so this script stays lightweight and usable standalone on
# any CSV without dragging in pybaseball just to read one dict.
DEFAULT_WEIGHTS = {"PW": 0.20, "MU": 0.35, "FM": 0.30, "BvP": 0.15}


def _tier(total: float) -> tuple:
    """Returns (label, css_var) for the overall conviction tier."""
    if total >= 75:
        return "FIRED", "var(--gold)"
    elif total >= 60:
        return "SOLID", "var(--green)"
    elif total >= 45:
        return "LEAN", "var(--amber)"
    else:
        return "COLD", "var(--red)"


def _signal_color(score: float) -> str:
    if score >= 65:
        return "var(--green)"
    elif score >= 45:
        return "var(--amber)"
    else:
        return "var(--red)"


def _park_border_color(pw_note: str) -> str:
    # PW_note looks like "park +21%, weather +3 (...)" -- pull the park
    # sign out to color the game card's edge green/red/neutral.
    try:
        park_part = pw_note.split(",")[0]  # "park +21%"
        val = int(park_part.replace("park", "").replace("%", "").strip())
        if val >= 8:
            return "var(--green)"
        elif val <= -8:
            return "var(--red)"
        return "var(--muted)"
    except Exception:
        return "var(--muted)"


def _player_card(row: dict) -> str:
    total = row.get("Total", 50)
    tier_label, tier_color = _tier(total)
    pw, mu, fm, bvp = row.get("PW", 50), row.get("MU", 50), row.get("FM", 50), row.get("BvP", 50)

    segments = ""
    for label, val in [("PW", pw), ("MU", mu), ("FM", fm), ("BVP", bvp)]:
        color = _signal_color(val)
        height = max(15, min(100, val))
        segments += f"""
        <div class="signal-seg">
          <div class="signal-track"><div class="signal-fill" style="height:{height}%; background:{color};"></div></div>
          <div class="signal-label">{label}</div>
        </div>"""

    lineup_badge = ""
    if row.get("lineup_source") == "projected":
        lineup_badge = '<span class="proj-badge" title="RotoWire projected lineup, not yet MLB-confirmed">PROJ</span>'

    notes = "<br>".join(filter(None, [
        row.get("PW_note", ""), row.get("MU_note", ""),
        row.get("FM_note", ""), row.get("BvP_note", ""),
    ]))

    return f"""
    <div class="player-row">
      <div class="player-id">
        <div class="player-name">{row.get('batter', '')} {lineup_badge}</div>
        <div class="player-team">{row.get('team', '')} · {row.get('pitcher_hand', '')}HB vs {row.get('pitcher_hand', '')}HP</div>
      </div>
      <div class="signal-bar">{segments}</div>
      <div class="total-chip" style="--tier-color:{tier_color};">
        <div class="total-num">{total:.0f}</div>
        <div class="total-tier">{tier_label}</div>
      </div>
      <details class="notes-toggle">
        <summary>notes</summary>
        <div class="notes-body">{notes}</div>
      </details>
    </div>"""


def _game_section(venue: str, group: pd.DataFrame) -> str:
    teams = group["team"].unique().tolist()
    pitchers = group["pitcher"].unique().tolist()
    matchup_label = " vs ".join(teams) if len(teams) <= 2 else ", ".join(teams)
    pitcher_label = " / ".join(pitchers)

    border_color = _park_border_color(group.iloc[0].get("PW_note", ""))

    group_sorted = group.sort_values("Total", ascending=False)
    cards = "".join(_player_card(row) for row in group_sorted.to_dict("records"))

    return f"""
    <section class="game-card" style="--edge-color:{border_color};">
      <div class="game-header">
        <div class="game-teams">{matchup_label}</div>
        <div class="game-venue">{venue}</div>
        <div class="game-pitchers">Facing: {pitcher_label}</div>
      </div>
      <div class="player-list">{cards}</div>
    </section>"""


def generate_html_report(df: pd.DataFrame, target_date: str, weights: dict = None) -> str:
    """
    Builds the full self-contained HTML page (CSS included, no external
    files needed except two Google Fonts links) from a results DataFrame
    -- either straight from build_candidates() or read back from a saved
    CSV. Returns the HTML as a string; caller decides whether to save it,
    return it to Streamlit, etc.
    """
    if df.empty:
        body = '<p class="empty-state">No candidates to show for this date.</p>'
    else:
        for col in ["PW", "MU", "FM", "BvP", "Total"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(50)

        if "Total" not in df.columns:
            w = weights or DEFAULT_WEIGHTS
            sub_cols = ["PW", "MU", "FM", "BvP"]
            if all(c in df.columns for c in sub_cols):
                df["Total"] = (
                    df["PW"] * w["PW"] + df["MU"] * w["MU"] +
                    df["FM"] * w["FM"] + df["BvP"] * w["BvP"]
                ).round(1)
                print("Note: this CSV didn't have a Total column (older file) -- computed it from PW/MU/FM/BvP using default weights.")
            else:
                df["Total"] = 50
                print("Note: this CSV is missing sub-score columns -- Total defaulted to 50 for all rows.")

        sections = []
        # group by venue -- note: on a rare doubleheader day, both games at
        # the same park will land in one section together rather than
        # splitting cleanly. Cosmetic edge case, not worth the complexity
        # of disambiguating for how rarely it happens.
        for venue, group in df.groupby("venue"):
            sections.append(_game_section(venue, group))
        body = "".join(sections)

    weight_str = ""
    if weights:
        weight_str = f"MU {weights['MU']*100:.0f}% · FM {weights['FM']*100:.0f}% · PW {weights['PW']*100:.0f}% · BvP {weights['BvP']*100:.0f}%"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HR Candidates — {target_date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0A0E1A;
    --panel: #131926;
    --panel-border: #1F2937;
    --chalk: #F1EDE4;
    --muted: #6B7280;
    --gold: #E8B923;
    --green: #34C77B;
    --amber: #F2A93C;
    --red: #FF5C5C;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--chalk);
    font-family: 'Inter', system-ui, sans-serif;
    margin: 0;
    padding: 0 16px 60px;
  }}
  .topbar {{
    padding: 32px 8px 20px;
    border-bottom: 2px solid var(--panel-border);
    margin-bottom: 28px;
  }}
  .topbar h1 {{
    font-family: 'Oswald', sans-serif;
    font-weight: 700;
    font-size: clamp(28px, 5vw, 42px);
    letter-spacing: 0.5px;
    margin: 0 0 4px;
    color: var(--chalk);
  }}
  .topbar h1 span {{ color: var(--gold); }}
  .topbar .subtitle {{
    color: var(--muted);
    font-size: 14px;
    font-family: 'JetBrains Mono', monospace;
  }}
  .game-card {{
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-left: 4px solid var(--edge-color, var(--muted));
    border-radius: 10px;
    margin: 0 auto 20px;
    max-width: 920px;
    padding: 18px 22px;
    animation: fadeUp 0.4s ease backwards;
  }}
  .game-card:nth-of-type(n) {{ animation-delay: calc(0.03s * var(--i, 0)); }}
  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .game-card {{ animation: none; }}
  }}
  .game-header {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 10px 16px;
    padding-bottom: 12px;
    margin-bottom: 10px;
    border-bottom: 1px solid var(--panel-border);
  }}
  .game-teams {{
    font-family: 'Oswald', sans-serif;
    font-weight: 600;
    font-size: 19px;
    color: var(--chalk);
  }}
  .game-venue {{ color: var(--muted); font-size: 13px; }}
  .game-pitchers {{ color: var(--muted); font-size: 13px; font-family: 'JetBrains Mono', monospace; }}
  .player-row {{
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    align-items: center;
    gap: 14px;
    padding: 10px 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    transition: background 0.15s ease;
  }}
  .player-row:last-child {{ border-bottom: none; }}
  .player-row:hover {{ background: rgba(255,255,255,0.02); }}
  .player-name {{
    font-weight: 600;
    font-size: 15px;
    color: var(--chalk);
  }}
  .proj-badge {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px;
    color: var(--amber);
    border: 1px solid var(--amber);
    border-radius: 4px;
    padding: 1px 4px;
    margin-left: 6px;
    vertical-align: middle;
  }}
  .player-team {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
  .signal-bar {{ display: flex; gap: 6px; }}
  .signal-seg {{ display: flex; flex-direction: column; align-items: center; width: 22px; }}
  .signal-track {{
    width: 8px;
    height: 32px;
    background: rgba(255,255,255,0.06);
    border-radius: 3px;
    display: flex;
    align-items: flex-end;
    overflow: hidden;
  }}
  .signal-fill {{ width: 100%; border-radius: 3px; }}
  .signal-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 8px;
    color: var(--muted);
    margin-top: 3px;
  }}
  .total-chip {{
    text-align: center;
    min-width: 56px;
    padding: 4px 8px;
    border-radius: 8px;
    border: 1px solid var(--tier-color, var(--muted));
  }}
  .total-num {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 20px;
    color: var(--tier-color, var(--chalk));
    line-height: 1.1;
  }}
  .total-tier {{
    font-family: 'Oswald', sans-serif;
    font-size: 9px;
    letter-spacing: 1px;
    color: var(--tier-color, var(--muted));
  }}
  .notes-toggle {{ font-size: 11px; color: var(--muted); }}
  .notes-toggle summary {{
    cursor: pointer;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--muted);
    list-style: none;
  }}
  .notes-toggle summary::-webkit-details-marker {{ display: none; }}
  .notes-body {{
    position: absolute;
    background: #0d1220;
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 11px;
    color: var(--chalk);
    max-width: 280px;
    margin-top: 6px;
    line-height: 1.5;
    z-index: 10;
  }}
  .empty-state {{ text-align: center; color: var(--muted); padding: 60px 0; }}
  @media (max-width: 640px) {{
    .player-row {{ grid-template-columns: 1fr auto; row-gap: 8px; }}
    .signal-bar {{ grid-column: 1 / -1; order: 3; }}
    .notes-toggle {{ grid-column: 1 / -1; order: 4; }}
  }}
</style>
</head>
<body>
  <div class="topbar">
    <h1>HR CANDIDATES <span>· {target_date}</span></h1>
    <div class="subtitle">Ranked by weighted Total{" · " + weight_str if weight_str else ""} — PW park/weather · MU matchup · FM form · BvP history</div>
  </div>
  {body}
</body>
</html>"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python mlb_hr_report.py <path_to_csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"Couldn't find {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    target_date = csv_path.stem.replace("hr_candidates_", "") or date.today().strftime("%Y-%m-%d")

    html = generate_html_report(df, target_date)
    out_path = csv_path.parent / f"hr_report_{target_date}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Saved visual report to {out_path}")

    try:
        webbrowser.open(f"file://{out_path.resolve()}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
