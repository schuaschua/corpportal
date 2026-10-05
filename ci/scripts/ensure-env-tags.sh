#!/usr/bin/env bash
# Infra pipeline, before Helm: an environment's first deploy needs <service>:<env> for every
# image. Any that no service pipeline published yet is seeded from <service>:latest.
set -euo pipefail
: "${REGISTRY:?}" "${ENVIRONMENT:?}"
acr="${REGISTRY%%.*}"

for svc in accounts-api payments-api insights-api outbox-relay portal-web; do
  if az acr manifest show-metadata --registry "$acr" --name "corportal/$svc:$ENVIRONMENT" --output none 2>/dev/null; then
    echo "corportal/$svc:$ENVIRONMENT present"
  else
    az acr import --name "$acr" --source "$REGISTRY/corportal/$svc:latest" \
      --image "corportal/$svc:$ENVIRONMENT" --output none
    echo "corportal/$svc:$ENVIRONMENT seeded from :latest"
  fi
done
