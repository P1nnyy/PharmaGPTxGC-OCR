# Same as edge.Dockerfile but bakes in the tunnel-mode Caddyfile (plain HTTP,
# no Let's Encrypt - Cloudflare terminates TLS at its edge).
# Build context is the repo root.

FROM node:20-alpine AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM caddy:2-alpine

COPY --from=build /src/dist /srv/frontend
COPY deploy/Caddyfile.tunnel /etc/caddy/Caddyfile
