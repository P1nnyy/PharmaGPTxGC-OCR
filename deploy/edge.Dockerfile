# The public edge of the stack: builds the SPA, then packages it together
# with Caddy and the Caddyfile into one image. Caddy serves the static build
# AND reverse-proxies API paths to the backend container (see Caddyfile), so
# the browser only ever talks to one origin - the frontend's relative fetch
# paths (/invoices, /products, ...) work unmodified in production, exactly as
# they do against the Vite dev proxy, and there is nothing to CORS-configure.
#
# Build context must be the repo root (not frontend/), since docker-compose
# passes `context: ..` from this file's directory - the frontend build only
# needs the frontend/ subtree, but keeping one build context for the whole
# stack keeps deploy/docker-compose.prod.yml simple.

FROM node:20-alpine AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM caddy:2-alpine

COPY --from=build /src/dist /srv/frontend
COPY deploy/Caddyfile /etc/caddy/Caddyfile
