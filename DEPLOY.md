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

At your registrar, create two records pointing at the server's public IPv4:

| Type | Name | Value          |
| ---- | ---- | -------------- |
| A    | `@`  | `<server IP>`  |
| A    | `www`| `<server IP>`  |

**Do this before step 5.** Caddy requests a Let's Encrypt certificate on
startup, and the HTTP-01 challenge only succeeds once `pharmagpt.co`
resolves to the machine answering on port 80. Nothing is served over HTTPS
until then.

Confirm it has propagated:

```bash
dig +short pharmagpt.co
```

Also make sure ports 80 and 443 are open — both TCP, plus 443/UDP for
HTTP/3. On a cloud provider this is a firewall/security-group setting, not
something the server config controls.

## 3. Get the code onto the server **[you]**

```bash
git clone <your repo url> pharmagpt
cd pharmagpt
```

## 4. Create the secrets file **[you]**

```bash
cp deploy/.env.prod.example deploy/.env.prod
```

Fill in every blank. `deploy/.env.prod` is gitignored and must never be
committed.

Generate the login password hash — Caddy will not accept a plaintext
password, so this is the only form the password takes on the server:

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
