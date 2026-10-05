---
title: 'Main Terraform stack (written and tested offline only, never applied)'
type: 'feature'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '544de39776ef19b268aa3ffcc84c38297dd031ad'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['inline-single']
review_loop_iteration: 0
context:
  - '{project-root}/docs/architecture/architecture.md'
  - '{project-root}/docs/architecture/azure.md'
  - '{project-root}/_bmad-output/specs/spec-corporate-portal-poc/stack.md'
  - '{project-root}/_bmad-output/specs/spec-corporate-portal-poc/cost-budget.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Jenkins has nothing to apply. Only `infra/bootstrap/` exists, and it creates the resource groups and Jenkins' identity, but no platform.

**Approach:**
- Write `infra/main/` as the whole Azure platform in Terraform.
- Prove it **offline only**: `fmt`, `validate`, Checkov, and `terraform test` with **mocked providers**.
- The owner's rule: "do as much as we can offline… dont put it on cloud".

## Boundaries & Constraints

**Always:**
- **Offline only:**
  - Never run `terraform plan`, `apply` or `import`, or any command that authenticates to Azure.
  - Use `terraform init -backend=false` for local work.
  - The backend is the `azurerm` block the bootstrap outputs (`stexampletfstate` / container `corportal` / `main.tfstate`, `use_msi`), filled in by Jenkins through `-backend-config`.
- **Resource groups:** use the existing bootstrap groups `rg-corportal-{primary,secondary,data}` as data sources. Never create resource groups (P-2); Jenkins only has rights inside them.
- **Principles:**
  - P-3 and P-5: storage shared keys off, SQL Entra-only admin, private endpoints plus private DNS zones for ADLS, SQL, Key Vault and Event Hubs, public network access off on those four.
  - P-7: Front Door Standard with an FDID ingress check.
  - P-9: tags `application`, `costCentre`, `dataClassification`, `environment`, `owner` and `destroyBy` on everything.
  - P-11: regions and names are variables.
- **Modules:**
  - `network` (VNet per region, subnets for AKS, private endpoints and the two Databricks subnets; NAT gateway only for Databricks);
  - `data` (ADLS Gen2 with HNS, Event Hubs Standard with 1 TU, Key Vault with RBAC, Azure SQL Basic with the failover group behind `enable_sql_failover`);
  - `aks` (AKS with node auto-provisioning, Azure CNI Overlay with Cilium, managed Istio add-on, OIDC issuer and workload identity, one system node pool D4s_v5, AcrPull on `exampleacr`, API server authorized IP ranges holding the Jenkins VM's public IP as a variable);
  - `databricks` (Premium, VNet-injected, no public IP, Access Connector with Storage Blob Data Contributor on ADLS; Unity Catalog metastore assignment as a variable);
  - `edge` (Front Door Standard with an origin per enabled region);
  - `identity` (a workload identity per service, federated to the AKS OIDC issuer; only the role assignments that bootstrap's allowed-roles condition permits).
- **Feature flags:**
  - `secondary_region_enabled` (false by default) adds the region 2 network and AKS, plus the Front Door origin.
  - `enable_sql_failover` (false by default).
- **Outputs Jenkins needs:** the AKS names and resource groups, the ACR login server, the Key Vault URI, the Event Hubs namespace FQDN, the SQL server FQDN or failover listener, the Databricks host, the Front Door endpoint and ID, and the per-service workload identity client IDs.
- **Tests:** `terraform test` files with `mock_provider "azurerm"` (Terraform ≥1.7; the installed version is 1.16.4) covering the matrix. **≤6 test runs.** Every test and scan is offline and runs in under 60 s.

**Never:**
- Any cloud call, including `plan`.
- Creating resource groups, management groups or role assignments outside the bootstrap's allowed-roles list (the condition would deny them anyway).
- Azure API Management, Front Door Premium, Firewall, Purview or Fabric.
- Always-on Databricks clusters (the bundle owns job clusters).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Default plan (mocked) | defaults | one region: AKS, the data services, Databricks, Front Door with 1 origin; no secondary resources; no SQL failover group | — |
| Saturday | `secondary_region_enabled=true` | a second VNet and AKS in northcentralus; Front Door with 2 origins | — |
| Failover dry run | `enable_sql_failover=true` | a secondary SQL server and a failover group; `sql_fqdn` output = the listener | — |
| Lockdown | any | the four data services have public access off and private endpoints; storage shared key off | — |
| Tags | any | every taggable resource has the 6 tag keys | — |
| Offline scan | `checkov -d infra/main` | runs; results reported (soft-fail) | — |

</frozen-after-approval>

## Code Map

- `infra/bootstrap/{main,variables,outputs}.tf`: the resource group names, the tag set (`local.tags`), the allowed-roles GUID list in the conditions, and the backend values. Mirror these names exactly; don't modify bootstrap.
- `databricks/databricks.yml`: its variables (catalog, the Event Hubs namespace) must match Terraform outputs.
- `deploy/helm/corportal/` (piece 5): the values expect the workload identity client IDs and endpoints. Keep the output names aligned.
- `Jenkinsfile` (piece 5): calls `infra/main/` with `-var secondary_region_enabled=…`; keep the variable names aligned.
- New: `infra/main/{versions,providers,variables,main,outputs}.tf`, `infra/main/modules/{network,data,aks,databricks,edge,identity}/`, `infra/main/tests/*.tftest.hcl`.

## Tasks & Acceptance

**Execution:**
- [x] `infra/main/**` -- the platform modules and root, as the Boundaries describe -- CAP-10, CAP-12, CAP-13, CAP-14.
- [x] `infra/main/tests/*.tftest.hcl` -- ≤6 mocked runs covering the matrix -- offline proof.
- [x] `Jenkinsfile`, `deploy/helm/**` -- align variable and output names if piece 5 guessed differently.
- [x] `README.md` -- an "Infrastructure" section: the bootstrap, then Jenkins, the flags and the Sunday destroy.

**Acceptance Criteria:**
- Given no Azure credentials, when `terraform -chdir=infra/main init -backend=false && terraform -chdir=infra/main validate && terraform -chdir=infra/main test` run, then all succeed.
- Given `stack-check.py`, when it runs, then it reports compliant (Terraform only, the agreed regions and tags).

## Implementation Notes

- Root: `versions.tf` (azurerm ~> 4.40, databricks ~> 1.80, empty `azurerm` backend), `providers.tf` (`resource_provider_registrations = "none"`, `storage_use_azuread`, `storage.data_plane_available = false` since storage is private and Jenkins is outside the VNet), `variables.tf`, `main.tf` (bootstrap resource groups and ACR as data sources; `local.tags` = bootstrap's tag set), `outputs.tf`.
- Modules as the Boundaries list. Additions needed to make them work together: VNet peering both ways when region 2 is on (region 2 reaches the region 1 private endpoints; DNS zones are linked to every VNet); a static public IP with DNS label per region for Kong's LoadBalancer, used as the Front Door origin (`kong_public_ips` output); an AKS subnet NSG that allows 80/443 only from `AzureFrontDoor.Backend`; a user-assigned control-plane identity and our own kubelet identity per cluster (Network Contributor on the subnet and the Kong IP, Managed Identity Operator on the kubelet identity, AcrPull for the kubelet: all on bootstrap's list); an `id-corportal-vault` workload identity with Key Vault Crypto User + Secrets User (Vault auto-unseal); Access Connector also gets Event Hubs Data Receiver (the bundle's Kafka read). The identity module validates role names against bootstrap's allowed list.
- AKS admin: Entra groups (`aks_admin_group_object_ids`, required), local accounts off, Kubernetes RBAC; SQL Entra admin defaults to the first of those groups.
- Output and variable names match what piece 5 already expects (`aks_clusters`, `front_door_id`, `eventhub_namespace_fqdn`, `sql_fqdn`, `databricks_host`, `istio_revision`, `workload_identity_client_ids`; `secondary_region_enabled`, `jenkins_public_ip`), so the Jenkinsfile and chart needed no renames.
- Tests: `tests/main.tftest.hcl`, 5 plan-only runs with `mock_provider` (azurerm with mocked data sources; databricks); modules expose `tagged`, `posture` / `security_posture` outputs for the assertions. Mutation check: turning storage shared keys on makes `lockdown` fail.
- Verified offline: `terraform fmt -check -recursive infra/`, `init -backend=false`, `validate`, `test` (5 passed, ~6 s), `uvx checkov -d infra/main --soft-fail --compact` (54 passed, 27 failed soft: PoC trade-offs such as no CMK, no SQL auditing, free AKS tier, public AKS API with authorized IPs, purge protection off), stack-check compliant with no warnings.

## Plan Change Log

- 2026-09-30: the databricks provider is added (only used when `databricks_metastore_id` is set) and mocked in the tests. The kubelet identity is user-assigned so AcrPull can be granted before the cluster pulls (and so the tests need no provider-computed block).

## Review Triage Log

- Pass 1 (one inline reviewer): 0 patched, 2 high carried forward.
  - high, carried forward: the Vault auto-unseal key isn't created, because Key Vault is private and Jenkins is outside the VNet. Piece 7 needs to either allow the Jenkins IP on Key Vault's network ACL or use Shamir unseal for the PoC.
  - high, verify in the cloud: creating the AKS node resource group and the Databricks managed resource group with Contributor at resource-group scope only; availability of Istio `asm-1-26` and NAP+Cilium+custom VNet in westus3; global name availability (`poc01`).
  - low, accepted: the 27 Checkov soft-fails are PoC trade-offs (no CMK, no SQL auditing, free AKS tier, public API behind authorized IPs).
  - Verified offline: fmt, validate, 5/5 mocked `terraform test` runs (and a deliberate regression is caught), stack-check compliant.

## Verification

**Commands:**
- `terraform fmt -check -recursive infra/` -- expected: clean.
- `terraform -chdir=infra/main init -backend=false && terraform -chdir=infra/main validate && terraform -chdir=infra/main test` -- expected: pass, ≤6 runs.
- `checkov -d infra/main --soft-fail --compact` (via `uvx checkov`) -- expected: runs.
- `uv run .claude/skills/agent-davinci/scripts/stack-check.py .` -- expected: compliant.
