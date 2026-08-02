# Deploying PharmaGPT to pharmagpt.co

Two containers behind one domain:

- **edge** — Caddy. Terminates TLS, gates the whole site behind a login,
  serves the built React app, and reverse-proxies API paths to the backend.
- **backend** — the FastAPI app. Never published to the host, so it is only
  reachable through the edge.

Because both are served from the same origin, the frontend's relative API
calls (`/invoices`, `/products`, …) work unchanged and there is no CORS
configuration anywhere.

Everything below marked **[you]** needs credentials or an account I don't
have; the rest is already in the repo.

---

## 1. Rent a server **[you]**

Any provider works. This is a CPU-only workload — extraction happens in
Azure Document Intelligence, and the database (Neo4j Aura) and image storage
(Cloudflare R2) are managed services — so it does not need to be large.
2 vCPU / 4 GB is comfortable.

Install Docker with Compose v2 (`docker compose`, not `docker-compose`):

```bash
curl -fsSL https://get.docker.com | sh
```

## 2. Point the domain at it **[you]**

In the Cloudflare dashboard → **DNS → Records**, create two A records
pointing at the server's public IPv4:

| Type | Name  | Value         | Proxy status              |
| ---- | ----- | ------------- | ------------------------- |
| A    | `@`   | `<server IP>` | **DNS only** (grey cloud) |
| A    | `www` | `<server IP>` | **DNS only** (grey cloud) |

### Start with the proxy OFF

Set both to **DNS only** — click the orange cloud so it turns grey.

This matters. With Cloudflare proxying (orange cloud), Let's Encrypt's
HTTP-01 challenge request never reaches your server — Cloudflare answers it
— so Caddy cannot obtain a certificate and nothing comes up. Grey cloud lets
the challenge through and Caddy gets a real certificate in seconds.

**Do this before step 5.** Caddy requests the certificate on startup, and
that only succeeds once `pharmagpt.co` resolves to the machine answering on
port 80.

Confirm it resolves to *your* IP (not a Cloudflare one — if you see
`104.x` or `172.67.x`, the proxy is still on):

```bash
dig +short pharmagpt.co
```

### Turning the proxy on later (optional)

Once the site is working over HTTPS, you can enable the orange cloud to get
Cloudflare's CDN and DDoS protection, which also hides your server's IP.
Two things must be true first, or the site breaks:

1. Caddy must already hold a valid certificate (i.e. it worked grey first).
2. Cloudflare **SSL/TLS → Overview → encryption mode** must be **Full
   (strict)**. On *Flexible*, Cloudflare talks to your origin over plain
   HTTP while Caddy redirects HTTP→HTTPS, producing an infinite redirect
   loop.

Certificate renewals will then start failing ~60 days later for the same
HTTP-01 reason. If you want to stay proxied long term, the fix is switching
Caddy to the DNS-01 challenge with a Cloudflare API token, which needs a
custom Caddy image (`xcaddy` with the Cloudflare DNS module). Not needed for
a private review deployment — grey cloud is fine.

### Firewall

Ports 80 and 443 must be open — both TCP, plus 443/UDP for HTTP/3. On a
cloud provider this is a firewall/security-group setting, not something the
server config controls.

## 3. Get the code onto the server **[you]**

```bash
git clone <your repo url> pharmagpt
cd pharmagpt
```

## 4. Create the secrets file **[you]**

Your existing local `.env` **does not change and does not get copied to the
server**. It is gitignored, and `.dockerignore` keeps it out of the image on
purpose. It stays on your laptop for local development.

The server gets a separate file, `deploy/.env.prod`, holding the same
service credentials plus three deployment-only settings:

```bash
cp deploy/.env.prod.example deploy/.env.prod
nano deploy/.env.prod
```

**Copy these across verbatim from your local `.env`** — same names, same
values:

```
DOCUMENTINTELLIGENCE_ENDPOINT
DOCUMENTINTELLIGENCE_API_KEY
AZURE_DI_MODEL_ID
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME
```

**Then add the three that only exist in production:**

```
DOMAIN=pharmagpt.co
BASIC_AUTH_USER=admin
BASIC_AUTH_HASH=<see below>
```

Nothing else needs changing. `EXTRACTION_ENGINE` defaults to `azure`, which
is what you want, and `AZURE_DI_SAVE_RAW` is a local debugging flag that
should stay off in production.

Since this deployment points at the **same Neo4j Aura database and same R2
bucket** as your local setup, invoices you scan on the server and invoices
you scanned locally are the same records. That is what you asked for, but it
does mean "Clear Bench" on the live site deletes your local data too.

### Generating the password hash

Caddy will not accept a plaintext password, so this is the only form the
password takes on the server:

```bash
docker run --rm caddy:2-alpine caddy hash-password
```

**Escape every `$` in the hash as `$$` when pasting it into
`deploy/.env.prod`.** Docker Compose performs variable interpolation on env
files, so a bcrypt hash like `$2a$14$s5Rb…` silently becomes `$2a$14/KD1P…`
— it loads without error and then rejects every login. Written correctly:

```
BASIC_AUTH_HASH=$$2a$$14$$s5RbBnGh14ty1H739AfhJOJl8PucDl2ewq/KD1P49zV/WwB8xNogW
```

`deploy/.env.prod` is gitignored and must never be committed.

## 5. Start it

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

First start takes a few minutes: it builds the frontend, installs Python
dependencies, and obtains the TLS certificate.

## 6. Verify

```bash
# Expect 401 - the auth gate is up
curl -o /dev/null -w "%{http_code}\n" https://pharmagpt.co/

# Expect 200 and JSON - the API is proxied correctly
curl -u <user>:<password> https://pharmagpt.co/health

# Expect 200 and HTML - client-side routes resolve on hard refresh
curl -o /dev/null -w "%{http_code}\n" -u <user>:<password> https://pharmagpt.co/catalogue
```

If `/health` returns HTML instead of JSON, the API paths are not matching —
check that the `handle` blocks in `deploy/Caddyfile` still list every prefix
the frontend calls.

## 7. Build the reference catalogue (optional)

Product enrichment needs the local drug-listing index, which is not in the
image (it is ~670k rows and gitignored). Build it inside the running
container:

```bash
docker compose -f deploy/docker-compose.prod.yml exec backend \
  python scripts/build_reference_index.py
```

Until this runs, the "Look up online" button reports that the index has not
been built. Everything else works without it.

---

## Updating a running deployment

```bash
git pull
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

## Logs

```bash
docker compose -f deploy/docker-compose.prod.yml logs -f backend
docker compose -f deploy/docker-compose.prod.yml logs -f edge
```

---

## Known limitation: authentication

The basic-auth gate is a **single shared password for the whole site**, not
a user system. Everyone who logs in sees the same data, and the backend
still treats every upload as belonging to one hardcoded pharmacy
(`DEFAULT_PHARMACY_ID`). There is no per-user login, no audit trail of who
changed what, and no isolation between pharmacies.

That is fine for your own use and for showing the product to people. It is
not sufficient before a second pharmacy's data is in the same deployment —
at that point their invoices, prices and purchase history would be visible
to each other. Real per-tenant auth is the next piece of work if this is
going to onboard other users.
