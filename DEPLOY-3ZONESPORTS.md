# Deploy Three-Zone Sports on Render

The public marketing site (`https://3zonesports.com`) is hosted on GitHub Pages.
The Render service runs the member portal, live games, schedules, archives, and
`/ops`.

## What You're Deploying

- **Application**: Three-Zone Sports control-plane MVP (Python)
- **Database**: SQLite (demo data; use PostgreSQL or a persistent disk for production)
- **Live Stream**: Demo mode (use Cloudflare Stream for production)
- **Member Auth**: Built-in username/password
- **Public Site**: Already live at 3zonesports.com (GitHub Pages)

## Prerequisites

1. Push this repository to GitHub.
2. Sign in to [Render](https://dashboard.render.com).

## Step 1: Create the Blueprint

1. Select **New** → **Blueprint**.
2. Connect GitHub and choose `3-Zone-Sports-`.
3. Select the branch containing this `render.yaml`.
4. Click **Apply**.

The root `render.yaml` sets the service root to `three-zone-mvp`, uses the
demo media rail, generates the application secrets, and checks `/api/health`.
Render supplies the web service `PORT`; do not hard-code `TZ_HTTP_PORT` to
`8000`, or the health check will target the wrong port.

## Step 2: Deploy

Render installs `three-zone-mvp/requirements.txt` and starts the service with
the Blueprint settings. The first deploy normally takes a few minutes.

## Step 3: Get Your Backend URL

After deployment completes:

1. Go to your service dashboard
2. At the top, you'll see a URL like: `https://three-zone-sports-xxxx.onrender.com`
3. Copy this URL

This is your **BACKEND_URL**.

## Step 4: Connect Frontend to Backend

Now the public website needs to know where the backend is.

1. Go to `https://github.com/bigdre816/3-Zone-Sports-`
2. Click the **docs** folder
3. Click **config.js**
4. Click the pencil icon to edit
5. Find this line (near the top):
   ```javascript
   BACKEND_URL: (() => {
     if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
       return 'http://localhost:8000';
     }
     // ...
   })(),
   ```

6. Replace the entire `BACKEND_URL` function with:
   ```javascript
   BACKEND_URL: 'https://three-zone-sports-xxxx.onrender.com',
   ```
   (Use your actual Render URL from Step 3)

7. Scroll down and click **Commit changes**
8. GitHub Pages will rebuild within 1-2 minutes

## Step 5: Test Sign-In

1. Open **3zonesports.com** in your browser
2. Look for the **Status** badge at the top right
3. It should show **Backend Online** (green)
4. Click **Member Sign In** button
5. You should be redirected to the member portal
6. Sign in with demo account:
   - **Username**: `demo-viewer`
   - **Password**: `change-me-viewer-local` (demo only; change in production)

## Step 6: Test Live Games

1. After signing in, click **Live** in the navigation
2. You should see demo games available
3. Click a game to watch the demo video

## Step 7: Test Schedules

1. Click **Schedules** in the navigation
2. You should see upcoming demo games

## Step 8: Test Archives

1. Click **Archives** in the navigation
2. You should see past demo games
3. Click a game to view the replay

## Step 9: Create Real Accounts (Optional)

1. On the member portal (after signing in), click your profile
2. Go to **Sign out**
3. On the login screen, click **Create account**
4. Enter:
   - Display name (your name)
   - Username (choose one)
   - Password (8+ characters)
5. Click **Create account**
6. You're now a member

## Step 10: Production Configuration (Later)

When ready to go live:

1. **Change demo passwords** (for `demo-owner`, `demo-worker`, etc.)
   - Set environment variables: `TZ_SEED_PASSWORD_VIEWER`, `TZ_SEED_PASSWORD_WORKER`, `TZ_SEED_PASSWORD_OWNER`
   - Redeploy on Render

2. **Add Cloudflare Stream** (for real live video)
   - Get account ID, API token, and webhook secret from Cloudflare
   - Set on Render: `TZ_CLOUDFLARE_ACCOUNT_ID`, `TZ_CLOUDFLARE_API_TOKEN`, `TZ_CLOUDFLARE_WEBHOOK_SECRET`
   - Set: `TZ_LIVE_MEDIA_PROVIDER=cloudflare`
   - Redeploy

3. **Enable XRPL** (for blockchain audit, optional)
   - Set: `TZ_XRPL_MODE=testnet` or `mainnet`
   - Provide signing credentials

4. **Custom Domain** (optional)
   - Add a subdomain like `app.3zonesports.com` or `api.3zonesports.com`
   - Render will generate a CNAME record
   - Add CNAME to your IONOS DNS

## Troubleshooting

### "Backend Offline" on Public Site

1. Check Render dashboard: Is the service running?
2. Go to **Logs** tab: Are there any errors?
3. Check the **BACKEND_URL** in config.js: Is it correct?
4. Wait 1-2 minutes for GitHub Pages to rebuild after changing config.js

### "Sign-in Failed" or "Permission Denied"

1. Make sure you're using the correct username/password
2. Default accounts:
   - `demo-viewer` / `change-me-viewer-local`
   - `demo-worker` / `change-me-worker-local`
   - `demo-owner` / `change-me-owner-local`
3. Check Render logs for database errors

### "No Live Games"

1. This is normal if no events are created
2. Go to `/ops` on the member portal
3. Sign in as `demo-worker`
4. Create a test event

### Database Issues

1. The database is stored at `/var/data/three_zone.sqlite3` on the persistent disk
2. Render deletes data when you delete the service or disk
3. To reset the database: Delete the web service, redeploy

## Support

For questions:
1. Check `three-zone-mvp/README.md` for app-specific help
2. Check Render docs: https://render.com/docs
3. Check Three-Zone app logs on Render dashboard

## Next Steps

- Set up custom domain (e.g., `app.3zonesports.com`)
- Configure Cloudflare Stream for live video
- Enable XRPL blockchain audit
- Scale to larger instance if needed
