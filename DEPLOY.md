# Putting this online for free (step by step)

This deploys `streamlit_app.py` as a real website with a URL you can visit
from any browser or phone, with a "Run model" button, a results table, and
a CSV download button. No server to manage, no monthly cost.

You'll need: a GitHub account (free) and about 10 minutes.

---

## Step 1 — Create a GitHub account (skip if you have one)

Go to **github.com**, click Sign Up, follow the prompts.

## Step 2 — Create a new repository

1. Once logged in, click the **+** icon top-right → **New repository**.
2. Name it something like `mlb-hr-model`.
3. Leave it **Public** (Streamlit's free tier is simplest with public repos —
   your code is visible, but nobody can run your app or see your results
   unless they go to your specific app URL, and your API key is never in
   the code itself, so this is fine).
4. Click **Create repository**.

## Step 3 — Upload the files (no command line needed)

On the new repo's page:

1. Click **Add file** → **Upload files**.
2. Drag in these four files: `mlb_hr_core.py`, `mlb_hr_model.py`,
   `streamlit_app.py`, `requirements.txt`.
3. **Do NOT upload `.env`** — that has your API key in it, and this repo
   is public. We'll add the key separately in Step 5, somewhere private.
4. Scroll down, click **Commit changes**.

## Step 4 — Deploy on Streamlit Community Cloud

1. Go to **share.streamlit.io**.
2. Click **Sign in with GitHub** and authorize it.
3. Click **Create app** (or **New app**).
4. Pick your `mlb-hr-model` repository, branch `main`.
5. For "Main file path," type: `streamlit_app.py`
6. Click **Deploy**.

It'll take a couple minutes to build the first time (installing pandas,
pybaseball, etc.). You'll see a live log while it works.

## Step 5 — Add your weather API key as a Secret

This is the private, secure way to give the app your key without putting
it in the public code:

1. On your app's page on Streamlit Cloud, click the **⋮** menu (or
   **Settings**) → **Secrets**.
2. Paste in exactly this (with your real key, from your local `.env` file):
   ```
   OPENWEATHER_API_KEY = "your-openweathermap-api-key-here"
   ```
3. Save. The app will automatically restart and pick it up.

## Step 6 — Use it

Your app now has a permanent URL like:

    https://mlb-hr-model-yourname.streamlit.app

Bookmark it, open it on your phone, share it — anyone with the link can
click "Run model" and get today's slate scored, no installation needed on
their end.

---

## Updating the model later

If you (or I) tweak the scoring logic:

1. Go to the file in your GitHub repo, click the pencil (edit) icon.
2. Paste in the new version, commit.
3. Streamlit Cloud auto-redetects the change and redeploys within a
   minute or two — nothing else to do.

## If something breaks

Click **Manage app** → you'll see the live application log, which shows
the actual Python error if the app crashes. Paste that error back to me
and I'll fix it.
