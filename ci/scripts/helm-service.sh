#!/usr/bin/env bash
# Service pipeline: roll one service to this build's image in every region of ENVIRONMENT,
# keeping everything else of the release (--reuse-values). No release yet (first run of the
# environment) = nothing to do: the infra pipeline installs the chart.
#   helm-service.sh <service> [reports/aks-clusters.txt]
set -euo pipefail

svc="${1:?usage: helm-service.sh <service>}"
clusters="${2:-reports/aks-clusters.txt}"
: "${IMAGE_TAG:?}"

while read -r region _rg _name; do
  [ -n "$region" ] || continue
  export KUBECONFIG="$PWD/.kube/$region"
  if ! helm status corportal --namespace corportal >/dev/null 2>&1; then
    echo "[$region] corportal not installed yet: the infra pipeline deploys it"
    continue
  fi
  helm upgrade corportal deploy/helm/corportal --namespace corportal --reuse-values \
    --set-string "services.$svc.imageTag=$IMAGE_TAG" --wait --timeout 10m --history-max 5
  echo "[$region] $svc -> $IMAGE_TAG"
done < "$clusters"
