# Deploy 3zonesports.com on Render

Homepage is already live: https://3zonesports.com/

You already created two Docker services. They failed because the repo had **no root Dockerfile** and the old image refused to start without production secrets.

That is fixed. You only need **one** service: **3-Zone-Sports-**. Ignore or delete **3-Zone-Api**.

## After this update is on GitHub

1. Open https://dashboard.render.com
2. Tap **3-Zone-Sports-**
3. Tap **Manual Deploy** → **Deploy latest commit**
4. Wait until Status is **Live** (a few minutes)
5. Tap the `onrender.com` URL at the top

Sign in:

- Username: `demo-viewer`
- Password: `change-me-viewer-local`

Send me that `onrender.com` link. I will hook Sign In on 3zonesports.com to it.
