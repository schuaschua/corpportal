#!/usr/bin/env bash
# Terraform for infra/main on the Jenkins VM agent, as id-corportal-jenkins (managed identity,
# ARM_USE_MSI; no stored keys, P-3). ARM_CLIENT_ID, ARM_SUBSCRIPTION_ID and ARM_TENANT_ID come
# from Jenkins' global environment (infra/bootstrap output `jenkins_env`).
# ENVIRONMENT (dev|prod) picks infra/main/environments/<env>.tfvars and the state <env>.tfstate.
#   terraform.sh plan    init + plan (or plan -destroy when DESTROY=true) -> tfplan,
#                        reports/tfplan.txt and reports/tfplan-summary.txt
#   terraform.sh apply   init + apply the saved tfplan, then reports/tf-outputs.json
#   terraform.sh output  init + reports/tf-outputs.json only (the service pipelines; no changes)
set -euo pipefail

action="${1:?usage: terraform.sh plan|apply|output}"
TF_DIR="${TF_DIR:-infra/main}"
env="${ENVIRONMENT:?ENVIRONMENT=dev|prod}"
case "$env" in dev|prod) ;; *) echo "ENVIRONMENT must be dev or prod" >&2; exit 2 ;; esac
if [ "$env" = "dev" ] && [ "${REGION_SECONDARY_ENABLED:-false}" = "true" ]; then
  echo "dev is one region: REGION_SECONDARY_ENABLED is prod only" >&2; exit 2
fi
: "${ARM_CLIENT_ID:?set ARM_* in Jenkins from the infra/bootstrap output jenkins_env}"
export ARM_USE_MSI=true TF_IN_AUTOMATION=true TF_INPUT=0
mkdir -p reports

tf() { terraform -chdir="$TF_DIR" "$@"; }

# Backend values: infra/bootstrap output `backend_config`.
tf init -input=false -reconfigure \
  -backend-config="resource_group_name=${TF_BACKEND_RESOURCE_GROUP:-rg-tfstate-sea}" \
  -backend-config="storage_account_name=${TF_BACKEND_STORAGE_ACCOUNT:-stexampletfstate}" \
  -backend-config="container_name=corportal" \
  -backend-config="key=$env.tfstate" \
  -backend-config="use_azuread_auth=true" \
  -backend-config="use_msi=true"

case "$action" in
  plan)
    # The AKS API server and Key Vault only accept the Jenkins VM (IP allow lists). Instance
    # metadata leaves a Standard SKU public IP empty, so fall back to the VM's outbound address,
    # which is what those firewalls see.
    ip="${JENKINS_PUBLIC_IP:-$(curl -fsS -H Metadata:true \
      'http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text' || true)}"
    [ -n "$ip" ] || ip="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
    [ -n "$ip" ] || { echo "Cannot find the Jenkins VM public IP: set JENKINS_PUBLIC_IP" >&2; exit 1; }
    mode=""
    if [ "${DESTROY:-false}" = "true" ]; then mode="-destroy"; fi
    # shellcheck disable=SC2086  # $mode is empty or one flag
    tf plan $mode -input=false -lock-timeout=5m -out=tfplan \
      -var-file="environments/$env.tfvars" \
      -var "secondary_region_enabled=${REGION_SECONDARY_ENABLED:-false}" \
      -var "jenkins_public_ip=${ip}"
    tf show -no-color tfplan > reports/tfplan.txt
    grep -E '^(Plan:|No changes\.|Changes to Outputs:)' reports/tfplan.txt > reports/tfplan-summary.txt \
      || echo "(no summary line; see tfplan.txt)" > reports/tfplan-summary.txt
    cat reports/tfplan-summary.txt
    ;;
  apply)
    tf apply -input=false -lock-timeout=5m tfplan
    if [ "${DESTROY:-false}" != "true" ]; then
      tf output -json > reports/tf-outputs.json
    fi
    ;;
  output)
    tf output -json > reports/tf-outputs.json
    ;;
  *)
    echo "usage: terraform.sh plan|apply|output" >&2
    exit 2
    ;;
esac
