# Deploy 3zonesports.com

Three pieces. One Render service.

| Piece | URL |
| --- | --- |
| Public site | https://3zonesports.com/ |
| Member portal | https://three-zone-sports.onrender.com/ |
| Back portal | https://three-zone-sports.onrender.com/ops |

The public site is already on GitHub Pages (`docs/`). Member portal and Back portal buttons on that site already point at the Render app. Do not create a second service. Do not point Pages at the repo root.

## One service

Use **3-Zone-Sports-** only. Ignore or delete **3-Zone-Api**.

Render must build the **root** `Dockerfile` from branch **`main`**. That image boots in demo mode, listens on Render’s `PORT`, and allows `https://3zonesports.com`.

Do not use `TZ_ENV=production` on this rail. Production mode refuses the demo logins and the service never becomes Live.

## Make Render Live

1. Open https://dashboard.render.com
2. Open **3-Zone-Sports-**
3. Confirm branch is **`main`**
4. Tap **Manual Deploy** → **Deploy latest commit**
5. Wait until Status is **Live**
6. Open https://three-zone-sports.onrender.com/api/health

That health URL must return JSON with `"status": "ok"`. If the tab spins and never loads, the deploy is still failed or stuck. Stay on this service and deploy `main` again. Do not add **3-Zone-Api**.

## Sign in

Member portal:

- Username: `demo-viewer`
- Password: `change-me-viewer-local`

Back portal (`/ops`):

- Username: `demo-owner`
- Password: `change-me-owner-local`

If Render gave you a different `onrender.com` URL, paste it once in the Connect box on https://3zonesports.com/ and tap Connect.

## If it is still down

- Service settings must be **Docker**, Dockerfile path `./Dockerfile`, health check `/api/health`.
- `TZ_ENV` must be `demo`.
- `TZ_ALLOWED_ORIGINS` must include `https://3zonesports.com` and `https://www.3zonesports.com`.
- GitHub Pages must stay on `/docs`. The repo-root `index.html` is not the public sports site.
