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

## 6. Point `app.3zonesports.com` at the member product (Lovable)

The signed-in product is **not** GitHub Pages and is **not** a Cloudflare DNS zone you manage. `3zonesports.com` nameservers stay at **IONOS** (`ns1026.ui-dns.com` and the other `ui-dns` hosts). The `server: cloudflare` header on the member app is Lovable’s edge, not a DNS record you edit in a Cloudflare dashboard.

Do this in **IONOS → 3zonesports.com → DNS** (same screen as step 2). Leave nameservers and MX alone.

Lovable’s current custom-domain setup: https://docs.lovable.dev/features/custom-domain

### A. `app` — A record

| Field | Type this |
| --- | --- |
| Type | `A` |
| Host name | `app` |
| Points to | `185.158.133.1` |

That address is Lovable’s documented edge IP. Do **not** CNAME `app` at GitHub Pages, Render, or `threezonesport.lovable.app` unless Lovable’s domain screen explicitly gives you a CNAME (only when you opt into “Domain uses Cloudflare or a similar proxy”).

### B. `_lovable.app` — TXT verification

| Field | Type this |
| --- | --- |
| Type | `TXT` |
| Host name | `_lovable.app` |
| Value | the `lovable_verify=…` string from Lovable → Project → Settings → Domains (copy it in full) |

IONOS host name is `_lovable.app`, not `_lovable.app.3zonesports.com`.

### C. Confirm it is live

In Lovable, `app.3zonesports.com` must show **Live / Active / Verified**, not pending.

From this repo:

```bash
python3 scripts/check_app_hostname.py
```

Public lookups that do not depend on your phone’s DNS cache:

- https://dns.google/query?name=app.3zonesports.com&type=A
- https://dns.google/query?name=_lovable.app.3zonesports.com&type=TXT
- https://www.nslookup.io/domains/app.3zonesports.com/dns-records/

You want `app.3zonesports.com` **A** `185.158.133.1`, HTTPS 200, certificate for `app.3zonesports.com`, and `threezonesport.lovable.app` redirecting to `https://app.3zonesports.com/`.

A web search that finds “nothing indexed” is **not** a DNS failure. Google Search can lag days after a hostname is live.

If a fetch tool reports NXDOMAIN while Google DNS already has the A record, retry with a browser on cellular, then Wi‑Fi. Phone resolvers and office Wi‑Fi can cache a miss for up to the 3600s TTL.

There is **no AAAA** for `app`. That is expected. IPv4 works; do not add a guessed IPv6 address.

### D. Do not mix Render into the apex

`3zonesports.com` must keep only GitHub Pages A records (`185.199.108–111.153`). An extra apex **A** to `216.24.57.1` is Render’s ingress and sends some visitors to the wrong host. Delete that row if it is still in IONOS.

## What this does not do

GitHub Pages (`docs/`) is the public catalog at https://3zonesports.com/. Sign-in, Live, My Zone, clips, and member scores run on https://app.3zonesports.com/ (Lovable). The Python API stays on Render (`three-zone-sports-1.onrender.com`) and is not linked as a public hostname.
