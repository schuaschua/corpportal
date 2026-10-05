# Portal SPA: build with Node, serve with nginx. Build context: web/
#   docker build -t corportal/portal-web web
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# Pick up patched Alpine packages (Trivy gate: e.g. OpenSSL CVE-2026-31789 in the base image).
RUN apk upgrade --no-cache
# nginx's entrypoint renders /etc/nginx/templates/*.template with envsubst (only variables
# that are set, so nginx's own $vars survive) and runs /docker-entrypoint.d/*.sh.
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.d/40-portal-config.sh /docker-entrypoint.d/40-portal-config.sh
RUN chmod +x /docker-entrypoint.d/40-portal-config.sh
COPY --from=build /web/dist /usr/share/nginx/html

# One image for every environment: runtime config comes from these at container start.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    ACCOUNTS_API_URL=http://accounts-api:8000 \
    PAYMENTS_API_URL=http://payments-api:8000 \
    INSIGHTS_API_URL=http://insights-api:8000 \
    VITE_AUTH_MODE=entra \
    VITE_LINEAGE_URL= \
    VITE_ENTRA_CLIENT_ID= \
    VITE_ENTRA_AUTHORITY= \
    VITE_ENTRA_KNOWN_AUTHORITY= \
    VITE_ENTRA_API_SCOPE=
EXPOSE 8080
