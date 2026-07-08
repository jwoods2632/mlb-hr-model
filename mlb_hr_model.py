"""
MLB Home Run Candidate Model -- Terminal Version
==================================================
Run this each morning (or afternoon) of a game day to get a ranked list of
today's best HR candidates, broken into 4 independent sub-scores:

  PW  - Park & Weather        (is the environment juicing or suppressing HRs)
  MU  - Matchup                (is this pitcher leaking to this batter's side)
  FM  - Form / streakiness     (is the bat hot right now, last 14 days)
  BvP - Batter vs this pitcher (direct history, regressed for sample size)

No blended score is produced on purpose -- look at all 4 and decide what you
trust today, the same way you would reading a cheat sheet by hand.

SETUP
-----
    pip install pybaseball pandas requests --break-system-packages

    Weather requires a free OpenWeatherMap API key (openweathermap.org/api).
    Put it in a file named .env in this same folder:
        OPENWEATHER_API_KEY=your_key_here
    The script picks it up automatically.

USAGE
-----
    python mlb_hr_model.py                  # today's slate
    python mlb_hr_model.py --date 2026-07-08 # a specific date

There is also a web version of this (streamlit_app.py) if you'd rather run
it with a button click in a browser instead of the terminal -- see the
DEPLOY.md file for how to put that online for free.
"""

import argparse
import os
import sys
from datetime import date

try:
    import mlb_hr_core as core
except ImportError:
    print("Couldn't find mlb_hr_core.py -- make sure it's in the same folder as this script.")
    sys.exit(1)

core.load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"),
                         help="Target date YYYY-MM-DD, defaults to today")
    parser.add_argument("--owm-key", default=None,
                         help="OpenWeatherMap API key (or set OPENWEATHER_API_KEY env var)")
    args = parser.parse_args()
    owm_key = args.owm_key or os.environ.get("OPENWEATHER_API_KEY")

    if owm_key:
        print("OpenWeatherMap key found -- live weather enabled.")
    else:
        print("No OpenWeatherMap key -- PW score will use park factor only.")

    out = core.build_candidates(args.date, owm_key, progress_callback=lambda m: print(f"  {m}"))

    if out.empty:
        print("\nNo candidates to show.")
        return

    fname = f"hr_candidates_{args.date}.csv"
    out.to_csv(fname, index=False)
    print(f"\nSaved {len(out)} candidates to {fname}\n")
    print(out[["batter", "team", "pitcher", "PW", "MU", "FM", "BvP"]].to_string(index=False))
    print("\nNOTE: check today's rain/delay risk manually for any flagged games --")
    print("that's not modeled numerically here.")


if __name__ == "__main__":
    main()
