# X FACTOR frontend — Vite build served by nginx.
#
# Build:  docker build -t xfactor-frontend ./frontend
# The build uses the default VITE_API_BASE_URL=/api; nginx proxies /api to the
# backend service, so no backend host or secret is compiled into the bundle.

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/healthz"]

CMD ["nginx", "-g", "daemon off;"]
