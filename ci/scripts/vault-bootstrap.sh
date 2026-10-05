#!/usr/bin/env bash
# Configure one region's HashiCorp Vault (called by platform-addons.sh, Jenkins VM agent):
#   1. init once (auto-unseal through Key Vault, one recovery key share); the root token and
#      the recovery key go straight into Key Vault as vault-root-token-<region> and
#      vault-recovery-key-<region> (P-3). An initialised Vault skips this step.
#   2. wait until the azurekeyvault seal has unsealed it
#   3. KV v2 at secret/, Kubernetes auth, one policy + role per service service account
#      (namespace corportal; role = service name, as the chart's Vault Agent annotations expect)
#   4. seed secret/corportal/<service> with DB_URL (only written when it changed)
# Every Vault command runs inside vault-0 with the token on stdin (never on a command line).
#   vault-bootstrap.sh <region> [reports/tf-outputs.json]
set -Eeuo pipefail

region="${1:?usage: vault-bootstrap.sh <region> [tf-outputs.json]}"
outputs="${2:-reports/tf-outputs.json}"
py() { python3 ci/scripts/tf_outputs.py "$@"; }
kc=".kube/$region"
kv="$(py get "$outputs" key_vault_name)"
sql_fqdn="$(py get "$outputs" sql_fqdn)"
sql_db="$(py get "$outputs" sql_database_name)"
# Services whose pods get Vault secrets (chart: `vault: true`).
services="accounts-api payments-api insights-api outbox-relay"

k() { kubectl --kubeconfig "$kc" --namespace vault "$@"; }
# Unauthenticated vault command in the server pod.
vault_cmd() { k exec vault-0 -c vault -- env VAULT_ADDR=http://127.0.0.1:8200 vault "$@"; }
# Authenticated: the token is read from stdin inside the pod.
vault_auth() {
  printf '%s\n' "$root_token" | k exec -i vault-0 -c vault -- sh -c \
    'read -r VAULT_TOKEN && export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200 && exec vault "$@"' vault "$@"
}
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

status() { vault_cmd status -format=json 2>/dev/null || true; }   # exit 2 = sealed

echo "[$region] waiting for vault-0"
state=""
for _ in $(seq 60); do
  state="$(status)"
  [ -n "$state" ] && break
  sleep 5
done
[ -n "$state" ] || { echo "[$region] vault-0 did not answer" >&2; exit 1; }

if [ "$(json 'd["initialized"]' <<<"$state")" = "True" ]; then
  echo "[$region] Vault already initialised: init skipped"
else
  echo "[$region] initialising Vault (1 recovery key share)"
  mkdir -p .work
  init=".work/vault-init-$region.json"
  (umask 077 && vault_cmd operator init -recovery-shares=1 -recovery-threshold=1 -format=json > "$init")
  # Keep the init file until both secrets are safely in Key Vault.
  (umask 077
   json 'd["root_token"]' < "$init" | tr -d '\n' > "$init.root"
   json 'd["recovery_keys_b64"][0]' < "$init" | tr -d '\n' > "$init.recovery")
  az keyvault secret set --vault-name "$kv" --name "vault-root-token-$region" --file "$init.root" --output none
  az keyvault secret set --vault-name "$kv" --name "vault-recovery-key-$region" --file "$init.recovery" --output none
  rm -f "$init" "$init.root" "$init.recovery"
fi

echo "[$region] waiting for the Key Vault auto-unseal"
for _ in $(seq 60); do
  [ "$(status | json 'd["sealed"]' 2>/dev/null || true)" = "False" ] && break
  sleep 5
done
[ "$(status | json 'd["sealed"]' 2>/dev/null || true)" = "False" ] || { echo "[$region] Vault is still sealed (check id-corportal-vault and the Key Vault key)" >&2; exit 1; }

root_token="$(az keyvault secret show --vault-name "$kv" --name "vault-root-token-$region" --query value --output tsv)" || {
  echo "[$region] Vault is initialised but Key Vault has no vault-root-token-$region" >&2; exit 1; }

if ! vault_auth secrets list -format=json | json '"secret/" in d' | grep -qx True; then
  vault_auth secrets enable -path=secret -version=2 kv
fi
if ! vault_auth auth list -format=json | json '"kubernetes/" in d' | grep -qx True; then
  vault_auth auth enable kubernetes
fi
# In-cluster Vault: its own service account token and CA review the pods' tokens.
vault_auth write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc >/dev/null

for svc in $services; do
  vault_auth write sys/policies/acl/"corportal-$svc" \
    policy="path \"secret/data/corportal/$svc\" { capabilities = [\"read\"] }" >/dev/null
  vault_auth write auth/kubernetes/role/"$svc" \
    bound_service_account_names="$svc" bound_service_account_namespaces=corportal \
    token_policies="corportal-$svc" token_ttl=1h token_max_ttl=4h >/dev/null

  # Entra-only SQL (no SQL logins, P-3): each service signs in as its own workload identity
  # (corp_common.db fetches the token; the client ID comes from the service account).
  db_url="mssql+pyodbc://@$sql_fqdn:1433/$sql_db?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&Authentication=ActiveDirectoryWorkloadIdentity"
  current="$(vault_auth kv get -field=DB_URL "secret/corportal/$svc" 2>/dev/null || true)"
  if [ "$current" != "$db_url" ]; then
    vault_auth kv put "secret/corportal/$svc" DB_URL="$db_url" >/dev/null
    echo "[$region] seeded secret/corportal/$svc"
  fi
done
echo "[$region] Vault ready: KV v2, Kubernetes auth, roles for: $services"
