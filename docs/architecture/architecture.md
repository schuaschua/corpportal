# Architecture: corportal

Agreed with the owner on 2026-09-30. `bmad-architecture` loads this file and the provider files beside it as
standing facts. Every AD fits the answers below and honours the principles, or names the principle it departs
from and why.

## Context

| # | Question | Answer | Source |
| --- | --- | --- | --- |
| 1a | Environment | Cloud | SPEC.md §Constraints |
| 1b | Cloud platforms | Azure ([azure.md](azure.md)) | SPEC.md §Constraints |
| 1c | Service model | Managed PaaS first; containers on managed Kubernetes for the microservices | stack.md §Compute, §Data |
| 1d | Regions and availability | Multi-region active-passive; single availability zone per region | SPEC.md §Constraints; single-zone is Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 2a | Policies and guidelines | None in the architecture folder; CBUAE regulator guidance applies (region `uae`) | regions.toml `uae` |
| 2b | Well-Architected priorities | 1 security, 2 cost optimization, 3 operational excellence, 4 reliability, 5 performance efficiency, 6 sustainability | Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 2c | Security level | Strict | Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 3a | Application type | Pure web | SPEC.md §Constraints (Fluent UI, five screens) |
| 3b | Architecture style | Microservices, event-driven data flow | stack.md §Compute, §Data |
| 3c | Migration | No | SPEC.md §Non-goals (no legacy integration) |
| 3d | Approved stack | Front end React + TypeScript + Fluent UI v9; back end Python 3.12 FastAPI; database Azure SQL; lake Delta on ADLS Gen2 | plan-core-data-and-apis.md, plan-portal-ui.md, stack.md |
| 4a | AI | Yes: own ML models built and trained (cash forecast, Isolation Forest anomaly detection), batch scoring, MLflow + Unity Catalog; data quality set by our seeded synthetic generator; platform Azure Databricks | SPEC.md CAP-7, CAP-8, CAP-9 |
| 4b | Analytics | Yes: batch medallion (bronze, silver, gold) on Azure Databricks | SPEC.md CAP-5, CAP-6 |

## Policies and guidelines
- None placed in this folder. The CBUAE documents for region `uae` (Guidelines for Financial Institutions Adopting Enabling Technologies; Guidance Note on Consumer Protection and Responsible Adoption and Use of AI) are the reference.

## DevOps

| # | Item | Answer | Source |
| --- | --- | --- | --- |
| 5a | CI | Jenkins on the existing VM, Kubernetes agents, Kaniko image builds | stack.md §Compute |
| 5b | CD / GitOps | Jenkins push deploys: Helm to AKS, Databricks Asset Bundles | Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 5c | Source control and branching | GitHub (`schuaschua/corpportal`), trunk-based on `main` | GitHub from the owner; trunk-based is Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 5d | Infrastructure as code | Terraform, through the same Jenkins | stack.md §Azure layout; infra/bootstrap |
| 6a | Environments | PoC; single subscription; synthetic data only | SPEC.md §Constraints |
| 6b | Approval gates and release strategy | tests pass; a named approver before each `terraform apply`; all at once | Da Vinci's pick, confirmed by the owner, 2026-09-30 |
| 6c | Secrets and pipeline security | managed identity, no stored cloud keys; Vault and Key Vault; scans: container image scan (Trivy), IaC infrastructure scan (Checkov) | identity from stack.md; scans are Da Vinci's pick, confirmed by the owner, 2026-09-30 |

## Principles

### P-1 Synthetic data only
- **Rule:** The solution must hold only generated synthetic data and must never be promoted to production.
- **Why:** No personal or customer data means no residency, consent or PCI exposure. Pillar: security.
- **Source:** SPEC.md §Constraints, §Non-goals.
- **Applies to:** the whole solution.

### P-2 Changes only through the pipeline
- **Rule:** Every Azure change must be made by Terraform run from Jenkins. The single exception is the Owner's one-off `infra/bootstrap` run, which creates what Jenkins may not create for itself.
- **Why:** Reproducible spin-up and teardown, and a clean least-privilege demonstration. Pillar: operational excellence.
- **Source:** 5d, 6b; SPEC.md CAP-10.
- **Applies to:** all infrastructure.

### P-3 No stored cloud keys
- **Rule:** Pipelines and workloads must authenticate by managed or workload identity. Application secrets must live only in HashiCorp Vault or Key Vault, never in code, images or the repository.
- **Why:** Showcase of real identity controls. Pillar: security.
- **Source:** 6c; SPEC.md §Constraints.
- **Applies to:** Jenkins, AKS workloads, Databricks.

### P-4 Company isolation from identity
- **Rule:** A caller must see only their own company's data, enforced both in the database (row-level security) and from the caller's identity, never from request input. Only the dedicated pipeline writer may bypass row-level security.
- **Why:** The cross-company blocked-access demonstration must hold. Pillar: security.
- **Source:** SPEC.md CAP-1, CAP-14.
- **Applies to:** every API and data store.

### P-6 Stateless services
- **Rule:** Services must keep no state in the cluster. All state lives in Azure SQL, Event Hubs or ADLS.
- **Why:** A region's compute can be removed while the other region keeps serving. Pillar: reliability.
- **Source:** SPEC.md §Constraints, CAP-12.
- **Applies to:** all microservices.

### P-8 Ledger first, lake for analytics
- **Rule:** Writes must go to the Azure SQL ledger and reach the lake only through the outbox and Event Hubs. The lake must not be used as a transactional store.
- **Why:** Balances and approvals stay consistent. Pillar: reliability.
- **Source:** SPEC.md §Constraints.
- **Applies to:** payments and the data platform.

### P-9 Cost ceiling and teardown
- **Rule:** PoC spend must stay at or below about USD 60. Everything must be destroyed by 2026-10-04. Databricks compute must never run outside test windows, and the secondary region must exist only on demo day.
- **Why:** the owner's budget. Pillar: cost optimization.
- **Source:** cost-budget.md; SPEC.md §Constraints.
- **Applies to:** all resources.

## Open questions
- None open. The US-region choice under a UAE regulator is recorded as a decision in [azure.md](azure.md) (P-11).

## Changes
| Date | Item | Change | Why |
| --- | --- | --- | --- |
| 2026-09-30 | All | First version | Agreed with the owner before Org Kit 1.13.0 builds |
| 2026-09-30 | 6c | Named the scan types beside the tools (no change of substance) | So stack-check recognises the agreed scans |
