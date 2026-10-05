#!/usr/bin/env bash
# Service pipeline, after Trivy: point the environment's moving tag (<service>:dev / :prod) at
# this build's image, in-registry (az acr import). The infra pipeline deploys <env> tags.
#   image-publish.sh <service>
set -euo pipefail
svc="${1:?usage: image-publish.sh <service>}"
: "${REGISTRY:?}" "${IMAGE_TAG:?}" "${ENVIRONMENT:?}"

az acr import --name "${REGISTRY%%.*}" --source "$REGISTRY/corportal/$svc:$IMAGE_TAG" \
  --image "corportal/$svc:$ENVIRONMENT" --force --output none
echo "$REGISTRY/corportal/$svc:$ENVIRONMENT -> $IMAGE_TAG"
