# syntax=docker/dockerfile:1
# Targets:  dev  — `next dev` with source bind-mounted
#           prod — Next standalone server (≈ no node_modules), non-root
FROM node:22-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

FROM base AS deps
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY . .
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time, and the
# /api rewrite target is resolved at build time too — pass them as build args.
ARG BACKEND_INTERNAL_URL=http://backend:8000
ARG NEXT_PUBLIC_WS_URL=""
ARG NEXT_PUBLIC_WIDGET_SCRIPT_URL=""
ARG NEXT_PUBLIC_WIDGET_API_URL=""
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_PUBLIC_WIDGET_SCRIPT_URL=${NEXT_PUBLIC_WIDGET_SCRIPT_URL} \
    NEXT_PUBLIC_WIDGET_API_URL=${NEXT_PUBLIC_WIDGET_API_URL}
RUN npm run build

FROM base AS prod
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["node", "server.js"]
