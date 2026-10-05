#!/usr/bin/env bash
# Deploy the corportal chart to one region of ENVIRONMENT (infra pipeline).
#   helm-deploy.sh <primary|secondary>
# Values: chart defaults, deploy/helm/values-<env>-<region>.yaml, the Terraform outputs
# (reports/values-tf-<region>.yaml from "Cluster access"), then global.imageTag=<env>: the
# moving tag every image gets once it passed Trivy in its service pipeline. A service that
# its own pipeline already deployed keeps that tag (services.<name>.imageTag, kept by
# --reset-then-reuse-values). DEMO_MODE=true moves the pods off spot nodes.
set -euo pipefail

region="${1:?usage: helm-deploy.sh <region>}"
env="${ENVIRONMENT:?ENVIRONMENT=dev|prod}"
export KUBECONFIG="$PWD/.kube/$region"

spot=true
[ "${DEMO_MODE:-false}" = "true" ] && spot=false

helm upgrade --install corportal deploy/helm/corportal \
  --namespace corportal --create-namespace --reset-then-reuse-values \
  -f "deploy/helm/values-$env-$region.yaml" \
  -f "reports/values-tf-$region.yaml" \
  --set-string global.imageTag="$env" \
  --set global.spot="$spot" \
  --wait --timeout 10m --history-max 5
helm status corportal --namespace corportal
