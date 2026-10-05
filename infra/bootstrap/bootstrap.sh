#!/usr/bin/env bash
# Run once, as subscription Owner, from your laptop:  ./infra/bootstrap/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")"

SUB=00000000-0000-0000-0000-000000000000
VM_RG=rg-jenkins
VM=jenkins-vm

az account set --subscription "$SUB"
terraform init
terraform apply -var "subscription_id=$SUB"

# Attach the identity to the existing Jenkins VM. Additive: another project's existing identities stay.
# Done with az, not Terraform, because the VM belongs to another Terraform stack.
# NOTE: if that stack is re-applied it may strip this identity; re-run the line below if so.
az vm identity assign -g "$VM_RG" -n "$VM" --identities "$(terraform output -raw jenkins_identity_id)"

echo
echo "Jenkins environment:"
terraform output -raw jenkins_env
