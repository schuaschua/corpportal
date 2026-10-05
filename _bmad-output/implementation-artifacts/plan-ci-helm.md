---
title: 'CI/CD: Helm chart and Jenkinsfile (parallel Kaniko builds, Trivy, Checkov, gated Terraform, deploy)'
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
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** All five images build locally, but nothing can build, scan or deploy them from Jenkins. DevOps answers 5a–6c commit us to Jenkins, Helm push deploys, Trivy and Checkov, and an owner approval before each `terraform apply`. The stack check flags missing scans as soon as a pipeline exists.

**Approach:**
- One Helm chart deploys the five services to AKS.
- One declarative `Jenkinsfile` does the rest:
  - tests;
  - Checkov on `infra/`;
  - Kaniko builds of the five images **in parallel**, each followed by Trivy, pushed to `exampleacr`;
  - Terraform plan, an owner approval gate, then apply;
  - Helm deploy and `databricks bundle deploy`.

## Boundaries & Constraints

**Always:**
- **Jenkins identity:** Jenkins signs in to Azure only with the VM's managed identity `id-corportal-jenkins` (`az login --identity --client-id`, and `ARM_USE_MSI` for Terraform). No stored keys (P-3).
- **Bootstrapping order:**
  - Stages up to and including Terraform run on the Jenkins **VM agent**, since the cluster doesn't exist on the first run.
  - Build, scan and deploy stages run on **Kubernetes pod agents** in AKS through the Jenkins Kubernetes plugin, once `terraform output` gives the cluster.
  - The first run is: VM → Terraform → AKS exists → pod stages.
- **Images:** tag with the git short SHA plus `latest`. Push to `exampleacr.azurecr.io/corportal/<service>`.
- **Scan gates:**
  - Trivy fails the build on CRITICAL vulnerabilities (fixed ones only).
  - Checkov runs soft-fail, reporting only, because the IaC is a PoC; its results are archived.
- **Terraform gate:** `input` approval, submitter `approver`, before `apply`, showing the plan summary (6b).
- **Parameters:**
  - `REGION_SECONDARY_ENABLED`, false by default, adds the region 2 stack on Saturday.
  - `DESTROY`, false by default, runs `terraform destroy` behind the same gate (P-9).
  - `DEMO_MODE` switches the batch cadence to 30 s and moves off spot nodes.
- **Helm chart:** one chart, with values per service:
  - image, env, probes on `/healthz`, 1 replica, resource requests sized for one D4s node plus Karpenter;
  - an Istio sidecar-injection label, a Kong `Ingress` with an FDID header check, and an annotation-driven Vault Agent for secrets (P-3);
  - pod anti-affinity off.
- **Local lint:** everything must pass `helm lint` and `helm template` locally.
- ≤3 new tests (only `helm template` smoke assertions if any; the project currently has 34).

**Never:**
- Writing the main Terraform stack (piece 6). The Jenkinsfile calls `infra/main/` by path, so it's fine that the folder doesn't exist yet.
- Running Jenkins or pushing images from this machine.
- GitHub Actions or any other CI (5a).
- ArgoCD or Flux (5b).
- Stored registry passwords. Kaniko authenticates to ACR with the node's kubelet identity or the workload identity.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| First run | no AKS yet | VM-agent stages run; pod stages wait until after the Terraform apply | a clear failure message if the approval is refused |
| Parallel build | 5 services | 5 Kaniko pods build concurrently; each gets a Trivy scan | one image failing fails the build and names the service |
| Critical CVE | Trivy finds a fixed CRITICAL | stage fails with the report archived | — |
| Destroy | `DESTROY=true` | plan -destroy → owner gate → destroy; no build or deploy | — |
| Stack check | pipelines now exist | `stack-check.py` reports compliant with no missing scans | — |

</frozen-after-approval>

## Code Map

- Existing images to build:
  - `services/{accounts-api,payments-api,insights-api,outbox-relay}/Dockerfile` (their build context is the repo root, as `docker-compose.yml` shows);
  - `web/Dockerfile` (its own context, with runtime `config.js` generated at start-up).
  - `databricks/Dockerfile.local` is local-only; don't build it in CI.
- `databricks/databricks.yml` is the bundle to deploy, with targets and variables for catalog, cadence and the Event Hubs namespace.
- `infra/bootstrap/outputs.tf`: `jenkins_env` and `backend_config`, which are the values Jenkins uses (`ARM_*`, the state container `corportal`).
- `.claude/skills/agent-davinci/scripts/stack-check.py` must stay compliant. It looks for a Jenkinsfile, Trivy and Checkov.
- New files:
  - `Jenkinsfile`;
  - `ci/pod-templates/{kaniko,tools}.yaml` (tools = az, terraform, helm, trivy, checkov, databricks CLI);
  - `ci/scripts/*.sh`, small helpers if needed;
  - `deploy/helm/corportal/` (`Chart.yaml`, `values.yaml`, templates for deployment, service, ingress and serviceaccount);
  - `deploy/helm/values-{primary,secondary}.yaml`.
- `README.md`: a "CI/CD" section with the first-run steps and the Jenkins plugins needed (Kubernetes, Pipeline, Git).

## Tasks & Acceptance

**Execution:**
- [x] `deploy/helm/corportal/**`, `deploy/helm/values-*.yaml` -- one chart for the five services -- 5b Helm push deploy.
- [x] `ci/pod-templates/*.yaml`, `ci/scripts/*` -- agent pods and helpers -- 5a Kubernetes agents and Kaniko.
- [x] `Jenkinsfile` -- stages, parameters and gates as the Boundaries describe -- 5a–6c.
- [x] `README.md` -- the CI/CD section.

**Acceptance Criteria:**
- Given the repository, when `helm lint deploy/helm/corportal` and `helm template` run with each values file, then both succeed.
- Given the Jenkinsfile, when it's validated with a Groovy parse check or `jenkinsfile-runner` (if one is available; otherwise by manual review), then it's syntactically valid.
- Given `stack-check.py`, when it runs, then it reports compliant with Trivy and Checkov found.

## Implementation Notes

- Chart: one Deployment, ServiceAccount (workload identity annotation when a client ID is set), Service and Kong Ingress per service; `konghq.com/headers.x-azure-fdid` on every Ingress, all-zero FDID default (fail closed); Vault Agent annotations render `/vault/secrets/env`, sourced by the container command; a Karpenter spot `NodePool` and spot nodeSelector while `global.spot` (DEMO_MODE turns it off); PeerAuthentication STRICT.
- `outbox-relay` has no HTTP endpoint, so it gets no probes, Service or Ingress; `portal-web` probes `/healthz` through the SPA fallback (200).
- Jenkinsfile: VM stages Prepare, Tests, Checkov, Terraform plan, Approve (no agent, `input` submitter `approver`, refusal -> clear error), Terraform apply, Cluster access; pod stages Images (declarative `matrix`, five Kaniko pods) and Release (tag latest, Helm per region, bundle). Pod stages also wait for `AKS_CLOUD_READY=true` (the Kubernetes cloud can only be configured once AKS exists).
- Kaniko pushes only the SHA tag (acr-env helper, workload identity); `latest` is added by crane after all five images pass Trivy, with a short-lived `az acr login --expose-token` token.
- Terraform output names the pipeline expects (piece 6 must match): `aks_clusters` (map region -> name, resource_group, location, fqdn, oidc_issuer_url), `front_door_id`, `eventhub_namespace_fqdn`, `sql_fqdn`, `databricks_host`, `istio_revision`, `workload_identity_client_ids`; variables `secondary_region_enabled`, `jenkins_public_ip`, `aks_admin_group_object_ids`.
- Verified: `helm lint` (both values files), `helm template` (both), Groovy parse of the Jenkinsfile in `groovy:4.0-jdk17` (no jenkinsfile-runner available), shellcheck of `ci/scripts`, stack-check compliant, `uv run pytest -q` (3 new chart smoke tests).

## Plan Change Log

- 2026-09-30: Terraform and Checkov run on the VM agent (Boundaries: everything up to Terraform on the VM), so the tools pod holds az, helm, crane and Python + Databricks CLI rather than terraform and checkov. Trivy runs in the Kaniko pod.

## Review Triage Log

- Pass 1 (one inline reviewer): 1 medium patched, 2 high carried forward.
  - medium, patch: stack-check didn't recognise Trivy and Checkov because 6c named only the tools. The architecture.md 6c wording now names the scan types, logged in its Changes; the check now finds container and IaC scans.
  - high, carried forward to a new piece 7: nothing installs Kong, HashiCorp Vault or Prometheus/Grafana in the cluster, but the chart depends on Kong and Vault. A Jenkins 'Platform add-ons' stage is needed.
  - high, manual, documented in README: the owner creates the Entra AKS admin group with `id-corportal-jenkins` in it; the owner federates the Jenkins identity per cluster; the Jenkins Kubernetes cloud is configured after the first apply.
  - low, verify in the cloud: Kaniko workload identity to ACR, the Databricks CLI image path, and kubelogin with MSI.

## Verification

**Commands:**
- `helm lint deploy/helm/corportal && helm template x deploy/helm/corportal -f deploy/helm/values-primary.yaml >/dev/null` -- expected: both succeed.
- `uv run .claude/skills/agent-davinci/scripts/stack-check.py .` -- expected: compliant.
- `uv run pytest -q` -- expected: all pass.
