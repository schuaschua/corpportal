#!/usr/bin/env bash
# Jenkins "Platform add-ons" stage (VM agent, managed identity id-corportal-jenkins, after
# "Cluster access"): install the in-cluster platform the corportal chart relies on, in every
# AKS cluster, with the charts pinned in deploy/platform/versions.env:
#   kong        Kong OSS, DB-less ingress controller, on the region's static public IP (P-7);
#               prod: the Front Door catch-all (kong-fdid-deny.yaml); dev (no Front Door): HTTPS
#               on Kong with cert-manager + a Let's Encrypt ClusterIssuer
#   vault       HashiCorp Vault, Raft, Key Vault auto-unseal, injector, Kubernetes auth (P-3)
#               then ci/scripts/vault-bootstrap.sh (init once, KV v2, roles, seeds)
#   monitoring  slim kube-prometheus-stack; Grafana ("Requests per second by region") only with GRAFANA_ENABLED=true;
#               prod: the Prometheus API through Kong at /prometheus (prometheus-api.yaml), key
#               from PROMETHEUS_API_KEY (Jenkins credential corportal-prometheus-api-key)
# Runs on the VM because Key Vault's firewall admits only the Jenkins VM's public IP.
# Re-runs are no-ops (helm upgrade --install; Vault init is skipped once done).
# Region 2 (if on) goes first, so the primary Prometheus can federate its internal LB.
# Needs az, kubectl, kubelogin, helm and python3 on the VM; kubeconfigs from cluster-access.sh.
#   platform-addons.sh [reports/tf-outputs.json]
set -Eeuo pipefail

outputs="${1:-reports/tf-outputs.json}"
: "${ARM_CLIENT_ID:?}"
py() { python3 ci/scripts/tf_outputs.py "$@"; }
# shellcheck source=/dev/null  # deploy/platform/versions.env (KEY=value lines)
. deploy/platform/versions.env

component="set-up"
trap 'echo "Platform add-ons FAILED: $component" >&2' ERR
step() { component="$1"; echo "=== $component"; }

step "Azure sign-in"
az login --identity --client-id "$ARM_CLIENT_ID" --output none
[ -n "${ARM_SUBSCRIPTION_ID:-}" ] && az account set --subscription "$ARM_SUBSCRIPTION_ID"

step "Helm repositories"
helm repo add kong "$KONG_CHART_REPO" --force-update >/dev/null
helm repo add hashicorp "$VAULT_CHART_REPO" --force-update >/dev/null
helm repo add prometheus-community "$MONITORING_CHART_REPO" --force-update >/dev/null
helm repo add jetstack "$CERT_MANAGER_CHART_REPO" --force-update >/dev/null
helm repo update >/dev/null

kv="$(py get "$outputs" key_vault_name)"
unseal_key="$(py get "$outputs" vault_unseal_key_name)"
vault_client_id="$(py get "$outputs" vault_identity_client_id)"
istio_rev="$(py get "$outputs" istio_revision)"
regions="$(py regions "$outputs" | sort -r)"   # secondary before primary
front_door="$(py get "$outputs" front_door_id)"   # empty in dev
# Grafana is off for now (small system node); GRAFANA_ENABLED=true brings it back on the primary.
grafana="${GRAFANA_ENABLED:-false}"
[ -z "$front_door" ] || : "${PROMETHEUS_API_KEY:?prod exposes Prometheus through Kong: needs PROMETHEUS_API_KEY}"

if [ "$grafana" = "true" ]; then
step "Grafana admin password (Key Vault $kv)"
if ! az keyvault secret show --vault-name "$kv" --name grafana-admin-password --query id --output none 2>/dev/null; then
  (
    umask 077 && mkdir -p .work
    trap 'rm -f .work/grafana-admin-password' EXIT
    openssl rand -base64 24 | tr -d '\n' > .work/grafana-admin-password
    az keyvault secret set --vault-name "$kv" --name grafana-admin-password \
      --file .work/grafana-admin-password --output none
  )
fi
fi

for region in $regions; do
  kc=".kube/$region"
  [ -f "$kc" ] || { echo "No kubeconfig $kc: run cluster-access.sh first" >&2; exit 1; }
  location="$(py get "$outputs" aks_clusters "$region" location)"
  kong_ip="$(py get "$outputs" kong_public_ips "$region" ip_address)"
  kong_rg="$(py get "$outputs" kong_public_ips "$region" resource_group)"

  kong_extra=()   # dev (no Front Door): Kong serves HTTPS itself
  [ -z "$front_door" ] && kong_extra=(-f deploy/platform/kong-values-dev.yaml)
  step "[$region] Kong ($KONG_CHART $KONG_CHART_VERSION)"
  helm upgrade --install kong "$KONG_CHART" --version "$KONG_CHART_VERSION" \
    --kubeconfig "$kc" --namespace kong --create-namespace \
    -f deploy/platform/kong-values.yaml \
    "${kong_extra[@]}" \
    --set-string "proxy.annotations.service\.beta\.kubernetes\.io/azure-load-balancer-ipv4=$kong_ip" \
    --set-string "proxy.annotations.service\.beta\.kubernetes\.io/azure-load-balancer-resource-group=$kong_rg" \
    --set-string "podLabels.istio\.io/rev=$istio_rev" \
    --wait --timeout 10m --history-max 5

  if [ -n "$front_door" ]; then
    kubectl --kubeconfig "$kc" --namespace kong apply -f deploy/platform/kong-fdid-deny.yaml >/dev/null
  else
    step "[$region] cert-manager ($CERT_MANAGER_CHART $CERT_MANAGER_CHART_VERSION)"
    helm upgrade --install cert-manager "$CERT_MANAGER_CHART" --version "$CERT_MANAGER_CHART_VERSION" \
      --kubeconfig "$kc" --namespace cert-manager --create-namespace \
      --set crds.enabled=true --wait --timeout 10m --history-max 5
    kubectl --kubeconfig "$kc" apply -f deploy/platform/letsencrypt-issuer.yaml >/dev/null
  fi

  step "[$region] Vault ($VAULT_CHART $VAULT_CHART_VERSION)"
  # No --wait: the pod is not Ready until vault-bootstrap.sh has initialised it.
  helm upgrade --install vault "$VAULT_CHART" --version "$VAULT_CHART_VERSION" \
    --kubeconfig "$kc" --namespace vault --create-namespace \
    -f deploy/platform/vault-values.yaml \
    --set-string "server.serviceAccount.annotations.azure\.workload\.identity/client-id=$vault_client_id" \
    --set-string "server.extraEnvironmentVars.VAULT_AZUREKEYVAULT_VAULT_NAME=$kv" \
    --set-string "server.extraEnvironmentVars.VAULT_AZUREKEYVAULT_KEY_NAME=$unseal_key" \
    --timeout 10m --history-max 5

  step "[$region] Vault bootstrap"
  ci/scripts/vault-bootstrap.sh "$region" "$outputs"

  step "[$region] monitoring ($MONITORING_CHART $MONITORING_CHART_VERSION)"
  mon_args=(--set-string "corportal.region=$location")
  # The cluster's region on the pod and container series (also once federated into the primary).
  region_label="{\"action\":\"replace\",\"targetLabel\":\"region\",\"replacement\":\"$location\"}"
  mon_args+=(--set-json "kubelet.serviceMonitor.cAdvisorRelabelings=[{\"action\":\"replace\",\"sourceLabels\":[\"__metrics_path__\"],\"targetLabel\":\"metrics_path\"},$region_label]"
             --set-json "kube-state-metrics.prometheus.monitor.relabelings=[$region_label]")
  if [ "$region" = "primary" ] && [ "$grafana" != "true" ]; then
    mon_args+=(--set grafana.enabled=false)
  fi
  if [ "$region" = "primary" ] && [ "$grafana" = "true" ]; then
    kubectl --kubeconfig "$kc" create namespace monitoring --dry-run=client -o yaml \
      | kubectl --kubeconfig "$kc" apply -f - >/dev/null
    kubectl --kubeconfig "$kc" --namespace monitoring create secret generic grafana-admin \
      --from-literal=admin-user=admin \
      --from-file=admin-password=<(az keyvault secret show --vault-name "$kv" --name grafana-admin-password --query value --output tsv | tr -d '\n') \
      --dry-run=client -o yaml | kubectl --kubeconfig "$kc" apply -f - >/dev/null
    mon_args+=(--set-file "grafana.dashboards.corportal.rps-by-region.json=deploy/platform/dashboards/rps-by-region.json")
  fi
  if [ "$region" = "primary" ]; then
    if grep -qx secondary <<<"$regions"; then
      target=""
      for _ in $(seq 60); do
        target="$(kubectl --kubeconfig .kube/secondary --namespace monitoring get service monitoring-kube-prometheus-prometheus \
          -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
        [ -n "$target" ] && break
        sleep 10
      done
      [ -n "$target" ] || { echo "Region 2 Prometheus has no internal load balancer IP" >&2; false; }
      mon_args+=(--set-string "corportal.federateTarget=$target:9090")
    fi
  else
    # Region 2: no Grafana (the primary shows both regions); Prometheus on an internal LB.
    mon_args+=(--set grafana.enabled=false --set prometheus.service.type=LoadBalancer)
  fi
  helm upgrade --install monitoring "$MONITORING_CHART" --version "$MONITORING_CHART_VERSION" \
    --kubeconfig "$kc" --namespace monitoring --create-namespace \
    -f deploy/platform/monitoring-values.yaml "${mon_args[@]}" \
    --wait --timeout 15m --history-max 5

  if [ -n "$front_door" ]; then
    step "[$region] Prometheus API through Kong"
    kubectl --kubeconfig "$kc" --namespace monitoring create secret generic prometheus-api-key \
      --from-file=key=<(printf '%s' "$PROMETHEUS_API_KEY") --dry-run=client -o yaml \
      | kubectl --kubeconfig "$kc" label --local -f - konghq.com/credential=key-auth -o yaml \
      | kubectl --kubeconfig "$kc" apply -f - >/dev/null
    sed "s|__FDID__|$front_door|" deploy/platform/prometheus-api.yaml \
      | kubectl --kubeconfig "$kc" apply -f - >/dev/null
  fi
done

component="done"
echo "Platform add-ons ready in: $(echo "$regions" | tr '\n' ' ')"
[ -z "$front_door" ] || echo "Prometheus API: https://$(py get "$outputs" front_door_endpoint_hostname)/prometheus/api/v1/query (header apikey)"
if [ "$grafana" = "true" ]; then
  echo "Grafana: kubectl --kubeconfig .kube/primary -n monitoring port-forward svc/monitoring-grafana 3000:80"
fi
