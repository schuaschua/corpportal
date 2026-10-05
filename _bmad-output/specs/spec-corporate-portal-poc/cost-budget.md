# Cost Budget (Wed 30 Sep → Sat 3 Oct 2026)

These are rough US list prices. Verify them with the Azure pricing calculator. The Jenkins VM and container registry already exist and are not included.

| Item | Assumption | ~Total |
|---|---|---|
| AKS primary | 1 regular D4s_v5 node + spot nodes | ~$20 |
| Databricks | ~8 hours in total, single node | ~$7 |
| Databricks NAT gateway | Egress for the VNet-injected workspace | ~$4 |
| Event Hubs Standard | 1 TU | ~$3 |
| Azure SQL | Basic, plus ~3 hours of the failover dry run | ~$4 |
| Private endpoints ×4 + DNS | | ~$4 |
| Storage, Key Vault, load balancer, IPs | | ~$5 |
| Region 2 AKS + Front Door Standard | Saturday only | ~$4 |
| **Total** | | **≈ $45–60** (about $40 if you stop AKS overnight) |

Cost rules:
- Run `az aks stop` overnight.
- Databricks auto-stops after 10 minutes and runs only during the integration window.
- Region 2 and Front Door are created on Saturday only.
- `terraform destroy` everything on Sunday 4 Oct.
