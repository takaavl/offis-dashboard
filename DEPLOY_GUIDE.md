# GitHub + Vercel — simple setup

## What is public vs private

- `data/team_dashboard.sqlite3` is the **compact public database** used by the site. It contains the structured stats and precomputed match insights, but no historical raw Tracker payloads.
- `data/private_full.sqlite3`, `data/private_raw/` and `data/Team's Dashboard.zip` are **local/private archives** and are ignored by Git.
- `/admin/` is protected by an admin code. On Vercel it is available for read-only admin/Data Health access, but imports remain disabled because Vercel is not a persistent SQLite write environment.

## First GitHub upload

From the `team_dashboard` folder:

```bash
git init
git add .
git commit -m "Initial Team Dashboard"
git branch -M main
```

Create a new **empty** repository on GitHub (do not add a README, .gitignore, or license), then copy its HTTPS URL and run:

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

## Deploy on Vercel

1. Sign in to Vercel with GitHub.
2. Click **Add New → Project**.
3. Import the GitHub repository you just created.
4. Leave **Root Directory** as `./`.
5. Do not set a Build Command or Output Directory. Vercel detects the root `main.py` FastAPI app automatically.
6. Click **Deploy**.
7. Before or after deployment, open **Project → Settings → Environment Variables** and add `ADMIN_CODE` with a strong private code. Optionally add `ADMIN_COOKIE_SECRET` with a long random value. Redeploy after changing environment variables.
8. Open the generated `*.vercel.app` URL.

Every future push to `main` will trigger a new production deployment automatically.

## Add a new official later

1. Run locally with `START_WINDOWS.bat` (or `python run.py`).
2. Open `http://127.0.0.1:8000/admin/` and sign in with your local admin code. On first launch, `START_WINDOWS.bat` asks you to create it.
3. Import the Tracker JSON and context.
4. Check the generated match/player/map pages.
5. Double-click `PREPARE_DEPLOY_WINDOWS.bat` (or run `python scripts/prepare_deploy.py`). This keeps the raw JSON private and compacts the deploy database.
6. Push the updated compact database:

```bash
git add .
git commit -m "Add new officials"
git push
```

Vercel redeploys from that commit.
