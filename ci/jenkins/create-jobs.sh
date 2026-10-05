#!/usr/bin/env bash
# Creates (or updates) corportal's multibranch jobs inside the existing `corportal` folder of the
# shared Jenkins. Nothing global changes (no plugins, no global config). Needs JENKINS_URL,
# JENKINS_USER, JENKINS_TOKEN (an API token), e.g. from .work/jenkins/jenkins.env.
#   corportal/infra          ci/Jenkinsfile.infra    Terraform, platform, database, deploy, Databricks
#   corportal/<service> x5   ci/Jenkinsfile.service  tests, image, Trivy, publish, deploy one service
#   create-jobs.sh [--delete-legacy]   also deletes the old single pipeline corportal/corportal
set -euo pipefail
: "${JENKINS_URL:?}" "${JENKINS_USER:?}" "${JENKINS_TOKEN:?}"
here="$(cd "$(dirname "$0")" && pwd)"
auth=(--user "$JENKINS_USER:$JENKINS_TOKEN" --fail --silent --show-error)
exists() { curl "${auth[@]}" -o /dev/null "$JENKINS_URL/$1/api/json" 2>/dev/null; }

job() {   # <name> <script path> <description>
  local xml; xml="$(sed -e "s|__NAME__|$1|g" -e "s|__SCRIPT__|$2|g" -e "s|__DESCRIPTION__|$3|g" "$here/multibranch.xml.tmpl")"
  if exists "job/corportal/job/$1"; then
    curl "${auth[@]}" -H "Content-Type: application/xml" -X POST --data-binary "$xml" "$JENKINS_URL/job/corportal/job/$1/config.xml"
    echo "updated corportal/$1"
  else
    curl "${auth[@]}" -H "Content-Type: application/xml" -X POST --data-binary "$xml" "$JENKINS_URL/job/corportal/createItem?name=$1"
    echo "created corportal/$1"
  fi
}

exists job/corportal || { echo "folder corportal is missing" >&2; exit 1; }
job infra ci/Jenkinsfile.infra "corportal infrastructure: Terraform (approval by approver), platform, database, full deploy, Databricks. main -&gt; prod, develop -&gt; dev."
for svc in accounts-api payments-api insights-api outbox-relay portal-web; do
  job "$svc" ci/Jenkinsfile.service "corportal $svc: tests, image, Trivy, deploy this service. main -&gt; prod, develop -&gt; dev."
done

if [ "${1:-}" = "--delete-legacy" ] && exists job/corportal/job/corportal; then
  curl "${auth[@]}" -X POST "$JENKINS_URL/job/corportal/job/corportal/doDelete"
  echo "deleted the legacy job corportal/corportal"
fi
