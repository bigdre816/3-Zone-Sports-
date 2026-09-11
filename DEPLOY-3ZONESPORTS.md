# Set up Render

The public site is already live from this repo (`bigdre816/3-Zone-Sports-`, GitHub Pages `/docs`): https://3zonesports.com/

Member portal and back portal run on **one** Render web service from `three-zone-mvp/`. That hostname is currently **503 / suspended by its owner** (`x-render-routing: suspend-by-user`). Resume it, or replace it with the Blueprint in this repo.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/bigdre816/3-Zone-Sports-)

## New (or replace the broken one)

1. Open https://render.com/deploy?repo=https://github.com/bigdre816/3-Zone-Sports-
2. Sign in to Render
3. Connect the GitHub repo **3-Zone-Sports-**
4. Apply Blueprint `render.yaml`
5. If Render asks for a card, that is the **0.5 CPU / 512 MB** plan so the app stays up (~$7/month). Free instances sleep and then show 503.
6. Wait until Status is **Live**
7. Open https://three-zone-sports.onrender.com/api/health

That health URL must return JSON with `"status": "ok"`.

Do **not** apply `three-zone-mvp/render.yaml`. That Python/production file is what created **3-Zone-Api**. Delete **3-Zone-Api** if it is still on the dashboard.

## Already have 3-Zone-Sports-

1. Open https://dashboard.render.com
2. Open **3-Zone-Sports-**
3. If it says Suspended, tap **Resume** (or Apply the Blueprint above so it is Docker + always-on)
4. Settings must be:
   - Branch **`main`**
   - Runtime **Docker**
   - Root Directory `three-zone-mvp`
   - Dockerfile path `./Dockerfile`
   - Docker context `.`
   - Health check `/api/health`
   - `TZ_ENV=demo`
   - Disk mounted at `/data` (SQLite + demo media). Without it, every redeploy wipes accounts.
5. Tap **Manual Deploy** → **Deploy latest commit**
6. Wait until **Live**, then open the health URL

Dockerfile path and Docker context are **relative to Root Directory**. If Root Directory is `three-zone-mvp`, both must stay `./Dockerfile` and `.`. Do not set either one to `three-zone-mvp` — that makes Render look for `three-zone-mvp/three-zone-mvp` and the build exits before Docker starts.

Do not use `TZ_ENV=production` on this rail. Production mode refuses the demo logins and the service never becomes Live.

## After it is Live

The public site at https://3zonesports.com/ loads Live, Schedule, and Archive by itself. Fans never paste a host, never see Render URLs, and never open an admin console from the homepage.

| Piece | Where |
| --- | --- |
| Public site | https://3zonesports.com/ |
| Member sign-in | https://3zonesports.com/app/ (redirects to the Render app) |
| Operator console | Render app `/ops` — unlisted, not linked from the public site |

Sign-in usernames and passwords for the demo rail live in `three-zone-mvp/README.md`. Do not print them on 3zonesports.com.

Camera: operator console → Event controls → **Start camera** → **Go live with this camera**. Keep that tab open.

## If it is still down

- Service settings must be **Docker**, Root Directory `three-zone-mvp`, Dockerfile path `./Dockerfile`, Docker context `.`, health check `/api/health`.
- `TZ_ENV` must be `demo`.
- `TZ_ALLOWED_ORIGINS` must include `https://3zonesports.com` and `https://www.3zonesports.com`.
- GitHub Pages must stay on `/docs` of **3-Zone-Sports-**. The repo-root `index.html` is not the public sports site.
- If health is HTML that says **Service Suspended**, the owner paused Render. Tap **Resume**, then **Manual Deploy**.
