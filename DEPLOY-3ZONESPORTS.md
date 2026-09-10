# Deploy 3zonesports.com on Render

The public homepage is already live: https://3zonesports.com/

Render runs the **member app** (sign in, live games, `/ops`). You already have a Render account.

## Do this on your phone

1. Open **https://dashboard.render.com** and sign in.
2. Tap **New** → **Blueprint**.
3. Connect GitHub if it asks. Pick the repo **The-system** (or **3-Zone-Sports-**).
4. Branch: **main** after this deploy file is merged, or the branch named `cursor/deploy-3zonesports-0707` until then.
5. Tap **Apply**. Wait until the service is green (a few minutes).
6. Tap the service. Copy the URL on top. It looks like:
   `https://three-zone-sports.onrender.com`

That URL **is** the full website. Open it.

Sign in:

- Username: `demo-viewer`
- Password: `change-me-viewer-local`

Staff /ops:

- Username: `demo-owner`
- Password: `change-me-owner-local`

## After it is green

Reply here with that `onrender.com` link. I will point https://3zonesports.com at it so Home → Sign In opens the live app.

Free Render apps go to sleep after a while. The first tap after sleep can take about a minute.
