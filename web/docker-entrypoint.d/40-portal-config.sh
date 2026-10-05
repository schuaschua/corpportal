#!/bin/sh
# Writes the SPA's runtime config from env, so one image serves every environment.
set -eu

json() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

cat > /usr/share/nginx/html/config.js <<JS
window.__PORTAL_CONFIG__ = {
  authMode: "$(json "${VITE_AUTH_MODE:-entra}")",
  lineageUrl: "$(json "${VITE_LINEAGE_URL:-}")",
  entraClientId: "$(json "${VITE_ENTRA_CLIENT_ID:-}")",
  entraAuthority: "$(json "${VITE_ENTRA_AUTHORITY:-}")",
  entraKnownAuthority: "$(json "${VITE_ENTRA_KNOWN_AUTHORITY:-}")",
  entraApiScope: "$(json "${VITE_ENTRA_API_SCOPE:-}")"
};
JS
echo "portal-web: config.js written (authMode=${VITE_AUTH_MODE:-entra})"
