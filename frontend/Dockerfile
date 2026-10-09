# AgentShield web dashboard - multi-stage build.
# Stage 1 builds the static SPA with Node; stage 2 serves it with nginx and proxies /api + /health
# to the FastAPI backend (compose service name "backend", port 8000). Container listens on 80.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/index.html || exit 1
