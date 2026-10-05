#!/usr/bin/env python3
"""Read `terraform output -json` (infra/main) for the Jenkinsfile. Standard library only.

  tf_outputs.py regions FILE              AKS region keys, one per line (primary [secondary])
  tf_outputs.py get FILE NAME [KEY ...]   one output value (nested map keys allowed), as text
  tf_outputs.py helm-values FILE REGION   a Helm values file (JSON is YAML) for that region

Output names (infra/main/outputs.tf): aks_clusters, front_door_id, eventhub_namespace_fqdn,
istio_revision, workload_identity_client_ids, databricks_host, sql_fqdn, sql_database_name;
for the platform add-ons also kong_public_ips, key_vault_name, vault_unseal_key_name,
vault_identity_client_id.
"""

from __future__ import annotations

import json
import sys


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return {k: v["value"] for k, v in json.load(f).items()}


def get(out: dict, name: str, *keys: str):
    value = out[name]
    for k in keys:
        value = value[k]
    return value


def helm_values(out: dict, region: str) -> dict:
    aks = out["aks_clusters"][region]
    return {
        "global": {
            "region": aks["location"],
            "frontDoorId": out.get("front_door_id") or "",  # empty in dev (no Front Door)
            "eventHubsNamespace": out.get("eventhub_namespace_fqdn", ""),
        },
        "istio": {"revision": out.get("istio_revision", "")},
        "services": {
            svc: {"workloadIdentityClientId": cid}
            for svc, cid in sorted(out.get("workload_identity_client_ids", {}).items())
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, path, *rest = argv[1:]
    out = load(path)
    if cmd == "regions":
        print("\n".join(sorted(out["aks_clusters"], key=lambda k: (k != "primary", k))))
    elif cmd == "get":
        value = get(out, *rest)
        print(value if isinstance(value, str) else json.dumps(value))
    elif cmd == "helm-values":
        print(json.dumps(helm_values(out, rest[0]), indent=2))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
