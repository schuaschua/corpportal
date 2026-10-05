#!/usr/bin/env bash
# Jenkins VM agent: build one service image with ACR Tasks (the build runs in the registry, so
# the VM needs no Docker) and push <IMAGE_REPO>/<service>:<IMAGE_TAG>. Signs in with the VM's
# managed identity (AcrPush from infra/bootstrap); no registry password.
# The environment's moving tag (<service>:dev / :prod) is added only after Trivy (image-publish.sh).
set -euo pipefail

svc="${1:?usage: image-build.sh <service>}"
: "${ARM_CLIENT_ID:?}" "${REGISTRY:?}" "${IMAGE_TAG:?}"

case "$svc" in
  accounts-api|payments-api|insights-api|outbox-relay) ctx="."; dockerfile="services/$svc/Dockerfile" ;;
  portal-web) ctx="web"; dockerfile="web/Dockerfile" ;;
  *) echo "unknown service: $svc" >&2; exit 2 ;;
esac

az login --identity --client-id "$ARM_CLIENT_ID" --output none
[ -n "${ARM_SUBSCRIPTION_ID:-}" ] && az account set --subscription "$ARM_SUBSCRIPTION_ID"

echo "Building $svc from $dockerfile (context $ctx) -> $REGISTRY/corportal/$svc:$IMAGE_TAG"
az acr build --registry "${REGISTRY%%.*}" --image "corportal/$svc:$IMAGE_TAG" \
  --file "$dockerfile" \
  --platform linux/amd64 --output none "$ctx" \
  || { echo "Image build failed: $svc" >&2; exit 1; }
