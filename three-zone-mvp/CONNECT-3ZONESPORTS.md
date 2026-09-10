# Connect 3zonesports.com to the public site

Plane: Three-Zone public hostname (operating-company site, not Moten vault/invention records).
Spec: public-release is privileged; this page is product marketing only.

You bought `3zonesports.com` at **IONOS**. GitHub Pages on **`bigdre816/3-Zone-Sports-`** already serves `/docs` on that domain with HTTPS enforced. If https://3zonesports.com/ already shows the Three-Zone public site, skip the DNS clicks below.

Do the GitHub folder click **before** changing DNS, or the Moten prototype at the repo root can go live on this domain.

## 1. Point GitHub Pages at the public Three-Zone folder

Open this link (signs you into GitHub, then opens Pages):

https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fbigdre816%2F3-Zone-Sports-%2Fsettings%2Fpages

On that page:

1. **Build and deployment** → **Source** = `Deploy from a branch`
2. **Branch** = `main`
3. **Folder** = `/docs` (not `/`)
4. **Custom domain** = `3zonesports.com` (already saved)
5. Click **Save**

GitHub’s own screens for this:

- Folder/source: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- Custom domain + the IPs you will type: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site#configuring-an-apex-domain

## 2. Log into IONOS and open DNS

Open:

https://login.ionos.com/?redirect_url=https%3A%2F%2Fmy.ionos.com%2Fdomains

Type your IONOS email (or customer ID). After login you land on **Domains & SSL**.

Next to **3zonesports.com**, click the **three-dot** icon → **DNS**.

Those clicks match IONOS’s live help (same DNS screens; ignore Vercel-specific IP values):

https://www.ionos.com/help/domains/connecting-a-domain-with-an-external-website/connecting-your-domain-to-vercel/

If a row says a **service** is managing the A record (website builder / Plesk), turn that service off first:

https://www.ionos.com/help/domains/general-information-about-dns-settings/managing-dns-services/

Do **not** change nameservers. Leave MX / mail records alone.

## 3. Type these records (this is the actual typing)

GitHub’s required values: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site#configuring-an-apex-domain

IONOS A-record clicks (Add record → A, Host name empty): same article as step 2.

IONOS CNAME clicks: https://www.ionos.com/help/domains/configuring-cname-records-for-subdomains/configuring-a-cname-record-for-a-subdomain/

IONOS conflict rule (you cannot keep the old A record and add a CNAME for the same host): https://www.ionos.com/help/domains/general-information-about-dns-settings/avoiding-dns-conflicts/

### A. Apex `3zonesports.com` — A records

Find the existing **A** record that points at `74.208.236.133`. Edit it.

| Field | Type this |
| --- | --- |
| Type | `A` |
| Host name | leave empty |
| Points to | `185.199.108.153` |

Then **Add record** three more times (Host name empty each time):

- `185.199.109.153`
- `185.199.110.153`
- `185.199.111.153`

If IONOS will only save **one** A record for the root, keep `185.199.108.153` and skip the extras. GitHub accepts a single A record.

Delete any other root **A** or **AAAA** that still points at IONOS.

### B. `www.3zonesports.com` — CNAME

If `www` already has an **A** record to `74.208.236.133`, delete that A record first.

**Add record** → **CNAME**:

| Field | Type this |
| --- | --- |
| Type | `CNAME` |
| Host name | `www` |
| Points to | `bigdre816.github.io` |

No `https://`. No trailing slash. No `/3-Zone-Sports-`.

## 4. Check that the internet picked it up

Open these (they load the live lookup for this domain):

- https://www.nslookup.io/domains/3zonesports.com/dns-records/
- https://www.nslookup.io/domains/www.3zonesports.com/dns-records/
- https://mxtoolbox.com/SuperTool.aspx?action=a%3a3zonesports.com&run=toolpage

You want `3zonesports.com` A records to show the `185.199.108–111.153` addresses, and `www` to show CNAME `bigdre816.github.io`.

IONOS is live immediately on their side; the rest of the internet can take up to an hour, sometimes longer.

## 5. Turn on HTTPS

Go back to:

https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fbigdre816%2F3-Zone-Sports-%2Fsettings%2Fpages

When GitHub shows the domain as DNS-ready, check **Enforce HTTPS**.

How that checkbox works: https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https

Then open:

- https://3zonesports.com/
- https://www.3zonesports.com/

You should see the Three-Zone public page, not an IONOS nginx 404.

## What this does not do

GitHub Pages can serve the public HTML in `docs/`. It cannot run the Python member app (`three-zone-mvp/`, sign-in, live playback). That app still needs a host (for example [Render](https://dashboard.render.com/) + [custom domain](https://render.com/docs/custom-domains)) in a later step.
