"""
MLB Home Run Candidate Model -- Web Version (Streamlit)
=========================================================
Same model as mlb_hr_model.py, but with a button-click web UI: pick a date,
click Run, watch it score today's slate, see a sortable table, download a
CSV. No terminal needed once this is deployed.

RUN LOCALLY
-----------
    pip install streamlit pybaseball pandas requests beautifulsoup4 --break-system-packages
    streamlit run streamlit_app.py
This opens a browser tab at localhost:8501 automatically.

DEPLOY TO A REAL WEBSITE (FREE)
--------------------------------
See DEPLOY.md in this same folder for the full walkthrough. Short version:
push this folder to a GitHub repo, connect it at share.streamlit.io, add
your OpenWeatherMap key in that site's "Secrets" panel (not in a .env file
when deployed -- Streamlit Cloud has its own secrets manager for this).
"""

import os
from datetime import date

import pandas as pd
import streamlit as st

import mlb_hr_core as core

st.set_page_config(page_title="MLB HR Candidate Model", page_icon="⚾", layout="wide")

core.load_dotenv()


def get_owm_key():
    # Streamlit Cloud secrets take priority (used once deployed), then a
    # local .env file (used when running on your own machine).
    try:
        if "OPENWEATHER_API_KEY" in st.secrets:
            return st.secrets["OPENWEATHER_API_KEY"]
    except Exception:
        pass
    return os.environ.get("OPENWEATHER_API_KEY")


st.title("MLB home run candidate model")
st.caption(
    "Four sub-scores blended into one **Total** ranking, weights adjustable below: "
    "**PW** park & weather · **MU** matchup/leak · **FM** form/streakiness · **BvP** history vs this pitcher"
)

col1, col2 = st.columns([1, 3])
with col1:
    target_date = st.date_input("Slate date", value=date.today())
with col2:
    st.write("")
    st.write("")
    run_clicked = st.button("Run model", type="primary")

with st.expander("Adjust score weights (recalculates instantly, no re-run needed)"):
    st.caption(
        "Defaults: MU 35% (most directly predictive), FM 30% (recent hot-bat signal), "
        "PW 20% (real but more a multiplier than a driver), BvP 15% (real when the sample's "
        "decent, but lifetime history vs one pitcher is often tiny). Should sum to 100%."
    )
    wcol1, wcol2, wcol3, wcol4 = st.columns(4)
    with wcol1:
        w_mu = st.slider("MU weight", 0, 100, int(core.SCORE_WEIGHTS["MU"] * 100), 5)
    with wcol2:
        w_fm = st.slider("FM weight", 0, 100, int(core.SCORE_WEIGHTS["FM"] * 100), 5)
    with wcol3:
        w_pw = st.slider("PW weight", 0, 100, int(core.SCORE_WEIGHTS["PW"] * 100), 5)
    with wcol4:
        w_bvp = st.slider("BvP weight", 0, 100, int(core.SCORE_WEIGHTS["BvP"] * 100), 5)

    weight_sum = w_mu + w_fm + w_pw + w_bvp
    if weight_sum != 100:
        st.warning(f"Weights sum to {weight_sum}%, not 100% — Total will be scaled off until these add up.", icon="⚠️")

    weights = {"MU": w_mu / 100, "FM": w_fm / 100, "PW": w_pw / 100, "BvP": w_bvp / 100}

owm_key = get_owm_key()
if owm_key:
    st.success("OpenWeatherMap key found — live weather enabled.", icon="✅")
else:
    st.warning(
        "No OpenWeatherMap key found — PW score will use park factor only. "
        "Add OPENWEATHER_API_KEY to a local .env file or to this app's Secrets if deployed.",
        icon="⚠️",
    )

if run_clicked:
    date_str = target_date.strftime("%Y-%m-%d")
    progress_area = st.empty()
    log_lines = []

    def progress_callback(msg):
        log_lines.append(msg)
        # keep the log short on screen -- last 8 lines
        progress_area.text("\n".join(log_lines[-8:]))

    with st.spinner("Scoring today's slate -- this pulls real data for every batter, takes a few minutes..."):
        results = core.build_candidates(date_str, owm_key, progress_callback=progress_callback, weights=weights)

    progress_area.empty()

    if results.empty:
        st.error("No candidates scored. Either there are no games today, or lineups aren't posted yet — try again closer to game time.")
    else:
        st.session_state["results"] = results
        st.session_state["results_date"] = date_str

if "results" in st.session_state:
    results = st.session_state["results"].copy()
    date_str = st.session_state["results_date"]

    # Recompute Total live from the already-fetched sub-scores whenever the
    # sliders move -- no need to re-pull Statcast data just to try new weights.
    if weight_sum > 0:
        results["Total"] = (
            results["PW"] * weights["PW"] + results["MU"] * weights["MU"] +
            results["FM"] * weights["FM"] + results["BvP"] * weights["BvP"]
        ).round(1)
    results = results.sort_values("Total", ascending=False).reset_index(drop=True)

    st.subheader(f"{len(results)} candidates for {date_str}")

    display_cols = ["batter", "team", "pitcher", "pitcher_hand", "venue", "lineup_source",
                     "Total", "PW", "MU", "FM", "BvP"]
    st.dataframe(
        results[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total": st.column_config.NumberColumn("Total", help="Weighted blend of PW/MU/FM/BvP"),
            "PW": st.column_config.NumberColumn("PW", help="Park & weather"),
            "MU": st.column_config.NumberColumn("MU", help="Matchup / leak"),
            "FM": st.column_config.NumberColumn("FM", help="Form / streakiness"),
            "BvP": st.column_config.NumberColumn("BvP", help="History vs this exact pitcher, all PAs counted"),
            "lineup_source": st.column_config.TextColumn(
                "Lineup", help="'confirmed' = MLB official, 'projected' = RotoWire early-day estimate"
            ),
        },
    )
    if (results["lineup_source"] == "projected").any():
        st.caption(
            "Rows marked **projected** are RotoWire's early-day expected lineup, not yet "
            "MLB's official confirmed one — worth a re-check closer to game time."
        )

    with st.expander("See the full notes behind each score"):
        note_cols = ["batter", "pitcher", "PW_note", "MU_note", "FM_note", "BvP_note"]
        st.dataframe(results[note_cols], use_container_width=True, hide_index=True)

    csv_bytes = results.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download full CSV",
        data=csv_bytes,
        file_name=f"hr_candidates_{date_str}.csv",
        mime="text/csv",
    )

    st.caption(
        "Reminder: rain/delay risk isn't modeled numerically here — worth a quick manual check "
        "for any game with a shaky forecast."
    )
