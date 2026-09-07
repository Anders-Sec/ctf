# syntax=docker/dockerfile:1

# --- build the SPA ---------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# No VITE_API_BASE_URL: the API client already targets the same-origin /api,
# so there is nothing to bake in at build time.
RUN npm run build

# --- serve -----------------------------------------------------------------
# The unprivileged image rather than stock nginx: stock starts as root and
# chowns its cache directories at boot, which fails under the pod's
# `capabilities.drop: ["ALL"]` and crash-loops the container. This one runs as
# uid 101 and chowns nothing, so the hardening stays as intended instead of
# being weakened to accommodate the image.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

# The Vite dev server is never shipped: Vite 5/6 rejects unknown Hosts behind a
# proxy, and a dev server has no business in front of 200 players.
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 8080, because a non-root process cannot bind 80.
EXPOSE 8080
