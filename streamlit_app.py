"""
MLB Home Run Candidate Model -- Web Version (Streamlit)
=========================================================
Same model as mlb_hr_model.py, but with a button-click web UI: pick a date,
click Run, watch it score today's slate, see a sortable table, download a
CSV. No terminal needed once this is deployed.

RUN LOCALLY
-----------
    pip install streamlit pybaseball pandas requests --break-system-packages
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
    "Four independent sub-scores, no blended number: "
    "**PW** park & weather · **MU** matchup/leak · **FM** form/streakiness · **BvP** history vs this pitcher"
)

col1, col2 = st.columns([1, 3])
with col1:
    target_date = st.date_input("Slate date", value=date.today())
with col2:
    st.write("")
    st.write("")
    run_clicked = st.button("Run model", type="primary")

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
        results = core.build_candidates(date_str, owm_key, progress_callback=progress_callback)

    progress_area.empty()

    if results.empty:
        st.error("No candidates scored. Either there are no games today, or lineups aren't posted yet — try again closer to game time.")
    else:
        st.session_state["results"] = results
        st.session_state["results_date"] = date_str

if "results" in st.session_state:
    results = st.session_state["results"]
    date_str = st.session_state["results_date"]

    st.subheader(f"{len(results)} candidates for {date_str}")

    display_cols = ["batter", "team", "pitcher", "pitcher_hand", "venue", "PW", "MU", "FM", "BvP"]
    st.dataframe(
        results[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "PW": st.column_config.NumberColumn("PW", help="Park & weather"),
            "MU": st.column_config.NumberColumn("MU", help="Matchup / leak"),
            "FM": st.column_config.NumberColumn("FM", help="Form / streakiness"),
        },
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
