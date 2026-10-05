---
title: 'Platform add-ons: Kong, HashiCorp Vault (Key Vault auto-unseal), Prometheus and Grafana via Jenkins (offline-tested)'
type: 'feature'
ticket: ''
created: '2026-09-30'
status: 'built'
route: 'full'
route_source: 'auto'
baseline_revision: '34061c435c6f2331cc4e3fc40cfb0f904e8008de'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['inline-single']
review_loop_iteration: 0
context:
  - '{project-root}/docs/architecture/architecture.md'
  - '{project-root}/docs/architecture/azure.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The corportal chart relies on Kong (ingress with the FDID check) and on the Vault Agent injector. Act 5 relies on Grafana (requests per second by region). Nothing installs any of them, and Vault's Key Vault auto-unseal key doesn't exist.

**Approach:**
- Add a Jenkins stage, **Platform add-ons**, that runs between *Cluster access* and *Images*.
- It Helm-installs the following, pinned per region, from `deploy/platform/`:
  - Kong OSS (DB-less ingress controller);
  - HashiCorp Vault (standalone, Raft on a PVC, `azurekeyvault` seal, agent injector, Kubernetes auth);
  - a slim kube-prometheus-stack with Grafana.
- Terraform creates the unseal key. Key Vault's firewall allows **only the Jenkins VM public IP**, alongside the private endpoint, so Jenkins can write the key while workloads still reach Key Vault privately.
- Everything is proven offline only.

## Boundaries & Constraints

**Always:**
- **Offline:** `helm lint`/`template`, `terraform validate`/`test`, shellcheck. No cloud calls and no `plan`.
- **Pinning and cost:** chart versions are pinned in `deploy/platform/versions.env`. Resource requests are small enough to share one D4s_v5 system node plus Karpenter spot nodes (P-9).
- **Kong:**
  - Its proxy Service is a LoadBalancer on the per-region static public IP (`kong_public_ips`) that already exists.
  - Global plugins: `request-termination` for any request whose `X-Azure-FDID` isn't ours (P-7), and `rate-limiting`.
  - **Token validation stays in the services** (`corp_common.auth`). Kong OSS has no OIDC plugin, so this is recorded as a stack.md deviation.
- **Vault:**
  - Init runs once from Jenkins with a single recovery key share, and the root token and recovery key go into Key Vault as secrets (P-3).
  - Kubernetes auth has one role per service service account.
  - It seeds each service's `DB_URL` and settings at `secret/corportal/<service>`, matching the chart's agent annotations.
  - Re-runs are idempotent: an already-initialised Vault skips init.
- **Grafana:**
  - One provisioned dashboard, "Requests per second by region", built from Istio request metrics labelled with the cluster region.
  - Admin password from Key Vault; reached by `kubectl port-forward` (no public exposure).
  - When region 2 is enabled, the primary Prometheus federates region 2's Prometheus over the VNet peering, through an internal load balancer.
- ≤4 new tests: helm-template smoke tests for the platform values, plus 1 Terraform run for the Key Vault key and firewall.

**Never:**
- Kong Enterprise or the OIDC plugin.
- Vault in dev mode.
- Exposing Grafana, Prometheus or Vault publicly.
- Applying anything, pushing images, or running Jenkins.
- Another CI or GitOps tool (5a, 5b).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| First install | a fresh cluster | Kong, Vault (initialised, unsealed through Key Vault, KV seeded, k8s auth roles) and monitoring installed before the Release stage | the stage fails with the failing component named |
| Re-run | everything already installed | `helm upgrade` is a no-op; Vault init skipped | — |
| Wrong FDID | a request to Kong without our FDID | 403 from `request-termination` | — |
| Region 2 on | `REGION_SECONDARY_ENABLED=true` | add-ons installed in both clusters; the primary Prometheus federates region 2; the dashboard shows both regions | — |
| Key Vault access | Terraform default | the unseal key exists; Key Vault firewall = Jenkins IP only, plus the private endpoint; public access otherwise denied | — |

</frozen-after-approval>

## Code Map

- `Jenkinsfile`: the stages are Prepare … `Cluster access` (line ~129) → **insert `Platform add-ons` here** → `Images` → `Release` (Helm primary and secondary per region).
- `ci/scripts/cluster-access.sh`: kubeconfig per region. Reuse it. `ci/scripts/tf_outputs.py` reads Terraform outputs such as `kong_public_ips`, the Key Vault name and the AKS names.
- `deploy/helm/corportal/`: the Ingress uses `ingressClassName: kong`. The Vault Agent annotations expect `secret/corportal/<service>` and `/vault/secrets/env`. Keep the new setup consistent with them.
- `infra/main/modules/data/`: Key Vault (RBAC, public access off, private endpoint). **Add** a `jenkins_ip_cidr` variable to its network ACL (`default_action = Deny`, `ip_rules = [jenkins_ip_cidr]`), the `azurerm_key_vault_key` unseal key, and the Vault workload identity (`id-corportal-vault`, which already exists in `modules/identity`) getting Key Vault Crypto User. That role is on bootstrap's allowed list.
- `infra/main/variables.tf`: `jenkins_ip_cidr` probably exists already for the AKS authorized IPs. Reuse the same variable.
- New files:
  - `deploy/platform/{versions.env,kong-values.yaml,vault-values.yaml,monitoring-values.yaml,dashboards/rps-by-region.json}`;
  - `ci/scripts/platform-addons.sh`;
  - `ci/scripts/vault-bootstrap.sh`.
- `_bmad-output/specs/spec-corporate-portal-poc/stack.md` says "Kong validating Entra tokens". Log the deviation in the README instead; the spec is edited only through bmad-spec.

## Tasks & Acceptance

**Execution:**
- [x] `infra/main/modules/data/**`, `infra/main/variables.tf`, `infra/main/tests/main.tftest.hcl` -- the unseal key, the Key Vault firewall, the Crypto User role, +1 test run.
- [x] `deploy/platform/**` -- values and dashboard.
- [x] `ci/scripts/platform-addons.sh`, `ci/scripts/vault-bootstrap.sh`, `Jenkinsfile` -- the stage.
- [x] `tests/test_helm_chart.py` -- ≤3 platform template smoke tests.
- [x] `README.md` -- the add-ons, how to reach Grafana, and the Kong token-validation deviation.

**Acceptance Criteria:**
- Given no cloud access, when `helm template` runs for each platform chart with our values (using the pinned charts pulled into `.work/`), then each renders.
- Given `terraform -chdir=infra/main test`, when it runs, then 6 of 6 pass.
- Given `stack-check.py`, when it runs, then it reports compliant.

## Implementation Notes

- Reused `jenkins_public_ip` (no new root variable): the data module takes `jenkins_ip_cidr = "<ip>/32"`. Key Vault `public_network_access_enabled` is now `true` (required for the IP rule to apply) with `default_action = Deny`, `bypass = None`, `ip_rules = [jenkins]`; the `lockdown` run now excludes Key Vault and the new `key_vault_unseal` run checks the firewall, key and private endpoint.
- The Vault identity's Key Vault Crypto User assignment already existed (root `identity` module, `vault/kv-crypto-user`); not duplicated in the data module.
- Added Jenkins **Key Vault Secrets Officer** on the vault (on bootstrap's list) so the stage can write the root token, recovery key and Grafana password. Creating `azurerm_key_vault_key` needs **Key Vault Crypto Officer**, which is not on bootstrap's list: README first-run step 1 now has the owner grant it once on `rg-corportal-data`.
- P-7 403: Kong's routes for corportal match only with our FDID; a catch-all Ingress in `kong` carries a `request-termination` (403) KongClusterPlugin. `rate-limiting` is a global KongClusterPlugin.
- Region label: a templated `additionalScrapeConfigs` job adds `region` to `istio_requests_total`; region 2 runs Prometheus on an internal LB and no Grafana; the primary federates it. Regions are processed region 2 first.
- Dry-run of both scripts against stubbed az/kubectl/helm (two runs, both regions): first run inits both Vaults and seeds, second run makes no Vault changes.

## Plan Change Log

## Review Triage Log

- Pass 1 (one inline reviewer): 2 low patched; 4 carried forward to the pre-cloud fix list.
  - low, patch: shellcheck SC2012 in `release-auth.sh`; the stale 404 comment in the corportal ingress template (now 403).
  - high, carried forward: creating the unseal key needs Key Vault Crypto Officer, which bootstrap doesn't allow. Bootstrap is **unapplied**, so fix it there: add Crypto Officer (14b46e9e-c2b7-41b4-b07b-48a6ebf60603) to the allowed roles, have main TF assign it to Jenkins on the Key Vault, and add a propagation wait. That avoids the README's manual step and keeps P-2.
  - high, carried forward: service SQL auth. ODBC `ActiveDirectoryMsi` probably doesn't support AKS workload identity. `corp_common.db` should fetch a token with azure-identity (WorkloadIdentityCredential) and pass it through `attrs_before` (SQL_COPT_SS_ACCESS_TOKEN).
  - medium, carried forward: the corportal chart needs `ingress.kubernetes.io/service-upstream: "true"` on its Services (Kong inside the mesh), and the pods need `traffic.sidecar.istio.io/excludeOutboundPorts: "8200"` so the Vault Agent init container can reach Vault.
  - accepted: Key Vault public access is on, limited to the Jenkins IP — the one P-5 exception, recorded in the README.

## Verification

**Commands:**
- `terraform fmt -check -recursive infra/ && terraform -chdir=infra/main validate && terraform -chdir=infra/main test` -- expected: pass, 6 runs.
- `uv run pytest -q` -- expected: pass.
- `shellcheck ci/scripts/*.sh` -- expected: clean.
- `uv run .claude/skills/agent-davinci/scripts/stack-check.py .` -- expected: compliant.
