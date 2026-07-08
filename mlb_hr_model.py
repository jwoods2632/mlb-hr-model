"""
MLB Home Run Candidate Model -- Terminal Version
==================================================
Run this each morning (or afternoon) of a game day to get a ranked list of
today's best HR candidates, broken into 4 independent sub-scores plus a
weighted Total for a clear-cut ranking:

  PW  - Park & Weather        (is the environment juicing or suppressing HRs)
  MU  - Matchup                (is this pitcher leaking to this batter's side)
  FM  - Form / streakiness     (is the bat hot right now, last 14 days)
  BvP - Batter vs this pitcher (every PA tracked, no minimum sample size --
                                 0 PA is stated explicitly, small samples are
                                 regressed toward neutral rather than excluded)

Default weights: MU 35%, FM 30%, PW 20%, BvP 15% (see SCORE_WEIGHTS in
mlb_hr_core.py for the reasoning). Override with --w-pw/--w-mu/--w-fm/--w-bvp,
must sum to 1.0.

SETUP
-----
    pip install pybaseball pandas requests beautifulsoup4 --break-system-packages

    Weather requires a free OpenWeatherMap API key (openweathermap.org/api).
    Put it in a file named .env in this same folder:
        OPENWEATHER_API_KEY=your_key_here
    The script picks it up automatically.

USAGE
-----
    python mlb_hr_model.py                          # today's slate, default weights
    python mlb_hr_model.py --date 2026-07-08         # a specific date
    python mlb_hr_model.py --w-pw 0.15 --w-mu 0.40 --w-fm 0.30 --w-bvp 0.15

There is also a web version of this (streamlit_app.py) if you'd rather run
it with a button click in a browser, with live weight sliders -- see the
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
    parser.add_argument("--w-pw", type=float, default=core.SCORE_WEIGHTS["PW"], help="Weight for Park & Weather")
    parser.add_argument("--w-mu", type=float, default=core.SCORE_WEIGHTS["MU"], help="Weight for Matchup")
    parser.add_argument("--w-fm", type=float, default=core.SCORE_WEIGHTS["FM"], help="Weight for Form")
    parser.add_argument("--w-bvp", type=float, default=core.SCORE_WEIGHTS["BvP"], help="Weight for BvP")
    args = parser.parse_args()
    owm_key = args.owm_key or os.environ.get("OPENWEATHER_API_KEY")

    weights = {"PW": args.w_pw, "MU": args.w_mu, "FM": args.w_fm, "BvP": args.w_bvp}
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 0.01:
        print(f"WARNING: weights sum to {total_weight:.2f}, not 1.0 -- Total scores will be scaled off. Continuing anyway.")

    if owm_key:
        print("OpenWeatherMap key found -- live weather enabled.")
    else:
        print("No OpenWeatherMap key -- PW score will use park factor only.")
    print(f"Weights: PW={weights['PW']:.2f} MU={weights['MU']:.2f} FM={weights['FM']:.2f} BvP={weights['BvP']:.2f}")

    out = core.build_candidates(args.date, owm_key, progress_callback=lambda m: print(f"  {m}"), weights=weights)

    if out.empty:
        print("\nNo candidates to show.")
        return

    fname = f"hr_candidates_{args.date}.csv"
    out.to_csv(fname, index=False)
    print(f"\nSaved {len(out)} candidates to {fname}\n")
    print(out[["batter", "team", "pitcher", "lineup_source", "Total", "PW", "MU", "FM", "BvP"]].to_string(index=False))
    print("\nNOTE: rows marked 'projected' are RotoWire's early-day expected lineup,")
    print("not an official confirmed one yet -- worth a re-check closer to game time.")
    print("Rain/delay risk also isn't modeled numerically here.")


if __name__ == "__main__":
    main()
