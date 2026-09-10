# Set up Render

The public site is already live: https://3zonesports.com/

Member portal and back portal run on **one** Render web service. That service is currently **503 / suspended**. Set it up with the Blueprint in this repo.

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
   - Dockerfile path `./Dockerfile`
   - Health check `/api/health`
   - `TZ_ENV=demo`
5. Tap **Manual Deploy** → **Deploy latest commit**
6. Wait until **Live**, then open the health URL

## After it is Live

| Piece | URL |
| --- | --- |
| Public site | https://3zonesports.com/ |
| Member portal | https://three-zone-sports.onrender.com/ |
| Back portal | https://three-zone-sports.onrender.com/ops |

Member: `demo-viewer` / `change-me-viewer-local`

Back portal: `demo-owner` / `change-me-owner-local`

Camera: Back portal → Event controls → **Start camera** → **Go live with this camera**. Keep that tab open.

If Render gave a different `onrender.com` host, paste it once in the Connect box on https://3zonesports.com/.
