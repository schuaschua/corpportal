#!/usr/bin/env bash
# One-off, as a tenant admin, from your laptop:  ./infra/entra/setup.sh
# Creates (or updates) the two corportal app registrations and the two demo users in the
# workforce tenant (example.com is a verified domain there), then prints the values for
# deploy/helm/values-<env>-primary.yaml (every environment) and the users' object IDs. Safe to re-run.
#   corportal-api     the APIs' audience: exposes the scope access_as_user (v2 tokens)
#   corportal-portal  the SPA: redirect URIs = prod (Front Door), dev (Kong's DNS name) and
#                     local dev, consented to that scope
set -euo pipefail

FD_HOST="${FD_HOST:-fde-corportal-poc01-0000000000000000.z03.azurefd.net}"          # prod
DEV_HOST="${DEV_HOST:-corportal-poc01d-primary.westus2.cloudapp.azure.com}"           # dev
DOMAIN="${DOMAIN:-example.com}"
TENANT="$(az account show --query tenantId -o tsv)"
graph() { az rest --only-show-errors --headers Content-Type=application/json "$@"; }

app_id() { az ad app list --display-name "$1" --query "[0].appId" -o tsv; }
ensure_app() {
  local id; id="$(app_id "$1")"
  [ -n "$id" ] || id="$(az ad app create --display-name "$1" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
  az ad sp show --id "$id" --query id -o tsv >/dev/null 2>&1 || az ad sp create --id "$id" --output none
  echo "$id"
}

# ---------- API
api="$(ensure_app corportal-api)"
api_obj="$(az ad app show --id "$api" --query id -o tsv)"
scope_id="$(az ad app show --id "$api" --query "api.oauth2PermissionScopes[?value=='access_as_user'].id | [0]" -o tsv)"
[ -n "$scope_id" ] || scope_id="$(uuidgen | tr 'A-Z' 'a-z')"
graph --method PATCH --url "https://graph.microsoft.com/v1.0/applications/$api_obj" --body "{
  \"identifierUris\": [\"api://$api\"],
  \"api\": {\"requestedAccessTokenVersion\": 2, \"oauth2PermissionScopes\": [{
    \"id\": \"$scope_id\", \"value\": \"access_as_user\", \"type\": \"User\", \"isEnabled\": true,
    \"adminConsentDisplayName\": \"Use corportal\", \"adminConsentDescription\": \"Call the corportal APIs as the signed-in user\",
    \"userConsentDisplayName\": \"Use corportal\", \"userConsentDescription\": \"Call the corportal APIs as you\"}]}
}"

# ---------- SPA
spa="$(ensure_app corportal-portal)"
spa_obj="$(az ad app show --id "$spa" --query id -o tsv)"
graph --method PATCH --url "https://graph.microsoft.com/v1.0/applications/$spa_obj" --body "{
  \"spa\": {\"redirectUris\": [\"https://$FD_HOST/\", \"https://$DEV_HOST/\", \"http://localhost:5173/\"]},
  \"requiredResourceAccess\": [{\"resourceAppId\": \"$api\", \"resourceAccess\": [{\"id\": \"$scope_id\", \"type\": \"Scope\"}]}]
}"
sleep 20   # the new permission must be visible before consenting
az ad app permission admin-consent --id "$spa"

# ---------- demo users (passwords printed once; change them after the demo)
user_oid() {   # <username> <display name>
  local upn="$1@$DOMAIN" id pw
  if ! id="$(az ad user show --id "$upn" --query id -o tsv 2>/dev/null)"; then
    pw="Cp-$(openssl rand -base64 18 | tr -d '/+=')"
    id="$(az ad user create --display-name "$2" --user-principal-name "$upn" \
      --password "$pw" --force-change-password-next-sign-in false --query id -o tsv)"
    echo "created $upn  password: $pw" >&2
  fi
  echo "$id"
}
priya_oid="$(user_oid priya "Priya Nair")"
tom_oid="$(user_oid tom "Tom Okafor")"

cat <<EOF

---- deploy/helm/values-{dev,prod}-primary.yaml (global.entra) ----
    tenantId: "$TENANT"
    audience: "$api"
    spaClientId: "$spa"
    authority: "https://login.microsoftonline.com/$TENANT"
    knownAuthority: ""
    apiScope: "api://$api/access_as_user"

---- users (ops.users.entra_oid) ----
priya  $priya_oid
tom    $tom_oid
EOF
