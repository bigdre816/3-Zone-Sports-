# Deploy Three-Zone Sports Backend to Render

This guide walks through deploying the Three-Zone Sports member app backend to Render.com. The public website (3zonesports.com) is already deployed on GitHub Pages. This deployment runs the member portal, live games, schedules, and archives.

## What You're Deploying

- **Application**: Three-Zone Sports control-plane MVP (Python)
- **Database**: SQLite (persistent disk on Render)
- **Live Stream**: Demo mode (use Cloudflare Stream for production)
- **Member Auth**: Built-in username/password
- **Public Site**: Already live at 3zonesports.com (GitHub Pages)

## Prerequisites

1. **GitHub**: This repository pushed to github.com
2. **Render Account**: Free or paid account at render.com
3. **Environment Secrets**: Two random 32+ character strings (created below)

## Step 1: Generate Required Secrets

You need two random secret strings. Generate them using Python:

```bash
python3 -c "import secrets; print('TZ_TOKEN_SECRET=' + secrets.token_urlsafe(40))"
python3 -c "import secrets; print('TZ_MEDIA_SERVICE_KEY=' + secrets.token_urlsafe(40))"
```

Save these two values. You'll enter them into Render in Step 4.

## Step 2: Connect GitHub to Render

1. Go to **render.com** and sign in (or create free account)
2. Click **Dashboard** (top left)
3. Click **New** (blue button, top right)
4. Select **Web Service**
5. Click **Connect Account** next to GitHub
6. Authorize Render to access your GitHub repositories
7. After authorization, you'll see a list of your repos
8. Find and select: `3-Zone-Sports-`
9. Click **Connect**

## Step 3: Configure the Service

On the "Create a new Web Service" page:

### Name
- Name: `three-zone-sports-api` (or similar)
- Region: Choose your region (US, EU, etc.)

### Build Settings
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `cd three-zone-mvp && python run.py`

### Environment Variables

Click **Environment** on the left sidebar. You'll see a form for environment variables.

Add these variables:

| Variable | Value |
|----------|-------|
| `TZ_ENV` | `production` |
| `TZ_HTTP_HOST` | `0.0.0.0` |
| `TZ_WS_HOST` | `0.0.0.0` |
| `TZ_HTTP_PORT` | `8000` |
| `TZ_WS_PORT` | `8765` |
| `TZ_DATABASE_PATH` | `/var/data/three_zone.sqlite3` |
| `TZ_TOKEN_SECRET` | *Paste the first secret you generated* |
| `TZ_MEDIA_SERVICE_KEY` | *Paste the second secret you generated* |
| `TZ_ALLOWED_ORIGINS` | `https://3zonesports.com,https://www.3zonesports.com` |
| `TZ_LIVE_MEDIA_PROVIDER` | `demo` |
| `TZ_UGC_MEDIA_PROVIDER` | `fake` |

### Disk

Scroll down to **Persistent Disk**.

- Click **Add Disk**
- Mount Path: `/var/data`
- Size: `10 GB` (sufficient for demo + small archives)

## Step 4: Configure Health Check

Scroll to **Health Check**:

- Health Check Path: `/api/health`
- Initial Delay: `30` seconds
- Timeout: `10` seconds

## Step 5: Deploy

1. Scroll to the bottom of the form
2. Click **Create Web Service**
3. Render will start building and deploying
4. You'll see a build log in real-time
5. After ~3-5 minutes, you should see "Your service is live" (or similar)

## Step 6: Get Your Backend URL

After deployment completes:

1. Go to your service dashboard
2. At the top, you'll see a URL like: `https://three-zone-sports-api-xxxx.onrender.com`
3. Copy this URL

This is your **BACKEND_URL**.

## Step 7: Connect Frontend to Backend

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
   BACKEND_URL: 'https://three-zone-sports-api-xxxx.onrender.com',
   ```
   (Use your actual Render URL from Step 6)

7. Scroll down and click **Commit changes**
8. GitHub Pages will rebuild within 1-2 minutes

## Step 8: Test Sign-In

1. Open **3zonesports.com** in your browser
2. Look for the **Status** badge at the top right
3. It should show **Backend Online** (green)
4. Click **Member Sign In** button
5. You should be redirected to the member portal
6. Sign in with demo account:
   - **Username**: `demo-viewer`
   - **Password**: `change-me-viewer-local` (demo only; change in production)

## Step 9: Test Live Games

1. After signing in, click **Live** in the navigation
2. You should see demo games available
3. Click a game to watch the demo video

## Step 10: Test Schedules

1. Click **Schedules** in the navigation
2. You should see upcoming demo games

## Step 11: Test Archives

1. Click **Archives** in the navigation
2. You should see past demo games
3. Click a game to view the replay

## Step 12: Create Real Accounts (Optional)

1. On the member portal (after signing in), click your profile
2. Go to **Sign out**
3. On the login screen, click **Create account**
4. Enter:
   - Display name (your name)
   - Username (choose one)
   - Password (8+ characters)
5. Click **Create account**
6. You're now a member

## Step 13: Production Configuration (Later)

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
