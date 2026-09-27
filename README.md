Team Dashboard v0.9

# Team Dashboard

FastAPI dashboard for the team's official-match history, roster context, maps, compositions, pistols, events and player performance.

## Run locally on Windows

Double-click `START_WINDOWS.bat`, or run:

```bash
py -m pip install -r requirements.txt
py run.py
```

Then open `http://127.0.0.1:8000`.

The dashboard is intentionally team-name neutral until a new official name is chosen.

## Local admin

Open `http://127.0.0.1:8000/admin` to add a future official from a Tracker JSON.

The admin can:
- add a map to an existing series or create a new series/event;
- auto-detect the team from known Riot aliases, with manual Red/Blue fallback;
- map borrowed accounts with `RiotID#TAG=CanonicalName` overrides;
- populate player stats, pistols, roster context, substitutions, leaderboard cache and teamplay insights;
- reject duplicate Tracker `match_id`s.

After adding data, run `PREPARE_DEPLOY_WINDOWS.bat` before committing. It removes raw JSON from the public SQLite database and keeps the deploy database compact.

## Public vs private data

- `data/team_dashboard.sqlite3` — compact deploy database, tracked by Git.
- `data/private_full.sqlite3` — original full historical/raw database, ignored by Git.
- `data/private_raw/` — future raw JSON archives added through Admin, ignored by Git.
- `data/Team's Dashboard.zip` — original source archive, ignored by Git.

The public DB is roughly **0.6 MB** instead of ~182 MB because match leaderboards and team insights are precomputed before raw payloads are removed.

## Vercel

The root `main.py` exposes the FastAPI `app` for Vercel zero-config detection. `.python-version` pins Python 3.12.

`/admin` is intentionally disabled on Vercel: bundled SQLite is suitable for reading, not durable production writes. Add data locally, prepare the deploy DB, commit and push; Vercel then redeploys the new snapshot.

See `DEPLOY_GUIDE.md` for the simple GitHub + Vercel walkthrough.

## Data / QA

- Historical dataset: 70 maps.
- Borrowed-account maps remain attributed to the actual canonical player.
- Match detail and map analytics work from compact precomputed caches; historical raw JSON is not required by the hosted site.

## Known limitations

- Agent/map artwork still uses remote URLs contained in Tracker exports.
- Admin is local-only by design; hosted persistent editing would require a hosted database such as Postgres/Supabase/Neon rather than bundled SQLite.


## Responsive

The public dashboard is responsive for desktop, tablet and phone. Mobile layouts prioritize readable cards, swipeable match tabs and scrollable dense data tables instead of hiding analytics.
