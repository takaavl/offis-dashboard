# Admin access

The public dashboard does not show Admin or Data Health.

## Local

On the first `START_WINDOWS.bat` launch, the script asks you to choose an admin code and stores it in:

`data/admin_codes.txt`

That file is ignored by Git. One code per line is supported if you want multiple admin codes.

Then open:

`http://127.0.0.1:8000/admin/`

## Vercel

In Vercel → Project → Settings → Environment Variables, add:

- `ADMIN_CODE` = your admin code
- optional `ADMIN_COOKIE_SECRET` = a long random string

Redeploy after saving the variables.

The hosted admin is read-only because the bundled SQLite filesystem is not a durable write store. Add matches locally, run `PREPARE_DEPLOY_WINDOWS.bat`, commit, and push.
