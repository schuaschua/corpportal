#!/usr/bin/env bash
# Jenkins VM agent: scan the image ACR just built, straight from the registry (Trivy from
# ci/scripts/vm-tools.sh). Fails on CRITICAL vulnerabilities that have a fix (6c); unfixed ones
# are reported by the table but don't fail. Report: reports/trivy-<service>.txt (archived).
set -euo pipefail

svc="${1:?usage: trivy-scan.sh <service>}"
: "${REGISTRY:?}" "${IMAGE_REPO:?}" "${IMAGE_TAG:?}"
mkdir -p reports

# Short-lived ACR token from the managed-identity sign-in of image-build.sh.
TRIVY_USERNAME=00000000-0000-0000-0000-000000000000
TRIVY_PASSWORD="$(az acr login --name "${REGISTRY%%.*}" --expose-token --query accessToken --output tsv)"
export TRIVY_USERNAME TRIVY_PASSWORD TRIVY_CACHE_DIR="$PWD/.trivy-cache"

rc=0
.bin/trivy image "$IMAGE_REPO/$svc:$IMAGE_TAG" --scanners vuln --severity CRITICAL --ignore-unfixed \
  --exit-code 1 --no-progress --format table --output "reports/trivy-$svc.txt" || rc=$?
cat "reports/trivy-$svc.txt" 2>/dev/null || true
if [ "$rc" -ne 0 ]; then
  echo "Trivy: $svc has fixed CRITICAL vulnerabilities (or the scan failed, exit $rc)" >&2
  exit 1
fi
echo "Trivy: $svc has no fixed CRITICAL vulnerabilities"
