"""Smoke tests for the Helm chart (deploy/helm/corportal): `helm template` renders what the
pipeline relies on. Skipped when helm is not installed."""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "corportal"
SERVICES = ["accounts-api", "payments-api", "insights-api", "outbox-relay", "portal-web"]

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def render(*args: str) -> str:
    return subprocess.run(
        ["helm", "template", "corportal", str(CHART), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.mark.parametrize("region", ["prod-primary", "prod-secondary"])
def test_renders_five_services_behind_front_door(region):
    out = render("-f", str(ROOT / "deploy" / "helm" / f"values-{region}.yaml"),
                 "--set", "global.imageTag=abc1234", "--set", "global.frontDoorId=fd-123")
    assert out.count("kind: Deployment") == 5
    for svc in SERVICES:
        assert f"image: exampleacr.azurecr.io/corportal/{svc}:abc1234" in out
    # P-7: every Ingress (the three APIs and the portal) matches only our Front Door.
    assert out.count("kind: Ingress") == 4
    assert out.count('konghq.com/headers.x-azure-fdid: "fd-123"') == 4
    assert out.count('sidecar.istio.io/inject: "true"') == 5
    # Kong inside the mesh routes to Services; Vault Agent init reaches Vault past the sidecar.
    assert out.count('ingress.kubernetes.io/service-upstream: "true"') == out.count("kind: Service\n")
    assert out.count('traffic.sidecar.istio.io/excludeOutboundPorts: "8200"') == out.count(
        'vault.hashicorp.com/agent-inject: "true"'
    ) > 0
    assert "karpenter.sh/capacity-type: spot" in out


def test_dev_is_https_on_kong_without_front_door():
    out = render("-f", str(ROOT / "deploy" / "helm" / "values-dev-primary.yaml"),
                 "--set", "global.imageTag=dev", "--set", "services.payments-api.imageTag=abc1234")
    assert out.count("kind: Ingress") == 4 and "x-azure-fdid" not in out
    assert out.count("secretName: corportal-tls") == 5  # 4 Ingresses + the one Certificate
    assert "kind: Certificate" in out and "name: letsencrypt" in out
    assert out.count('"corportal-poc01d-primary.westus2.cloudapp.azure.com"') >= 5
    # The per-service pipelines move one service's tag; the rest keep the environment's tag.
    assert "corportal/payments-api:abc1234" in out and "corportal/accounts-api:dev" in out


def test_fails_closed_without_front_door_or_tls():
    with pytest.raises(subprocess.CalledProcessError) as err:
        render()
    assert "global.frontDoorId" in err.value.stderr


def test_demo_mode_moves_off_spot():
    out = render("--set", "global.spot=false", "--set", "global.frontDoorId=fd-123")
    assert "spot" not in out.replace("spotCpuLimit", "")
    assert "kind: NodePool" not in out


# ---------- platform add-ons (deploy/platform): the pinned upstream charts with our values.
# Offline: the charts must already be pulled into .work/charts (README "Platform add-ons");
# a test is skipped when its pinned chart is not there.
PLATFORM = ROOT / "deploy" / "platform"
PULLED = ROOT / ".work" / "charts"


def pinned(name: str) -> Path:
    versions = dict(
        line.split("=", 1) for line in (PLATFORM / "versions.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    key = {"kong": "KONG", "vault": "VAULT", "kube-prometheus-stack": "MONITORING"}[name]
    chart = PULLED / name
    meta = chart / "Chart.yaml"
    if not meta.exists() or f"version: {versions[f'{key}_CHART_VERSION']}" not in meta.read_text():
        pytest.skip(f"pinned chart {name} {versions[f'{key}_CHART_VERSION']} not pulled into .work/charts")
    return chart


def render_platform(release: str, name: str, values: str, namespace: str, *args: str) -> str:
    return subprocess.run(
        ["helm", "template", release, str(pinned(name)), "--namespace", namespace,
         "-f", str(PLATFORM / values), *args],
        check=True, capture_output=True, text=True,
    ).stdout


def test_kong_oss_front_door_only():
    out = render_platform(
        "kong", "kong", "kong-values.yaml", "kong",
        "--set-string", r"proxy.annotations.service\.beta\.kubernetes\.io/azure-load-balancer-ipv4=203.0.113.20",
        "--set-string", r"podLabels.istio\.io/rev=asm-1-29",
    )
    assert "image: kong:" in out and "kong-gateway" not in out  # OSS, never Enterprise
    assert 'value: "off"' in out  # DB-less
    assert "type: LoadBalancer" in out and 'azure-load-balancer-ipv4: "203.0.113.20"' in out
    assert out.count("type: LoadBalancer") == 1 and "NodePort" not in out  # proxy only
    # P-7 (prod): requests without our FDID reach only the catch-all route, which answers 403.
    fdid = (PLATFORM / "kong-fdid-deny.yaml").read_text()
    assert "plugin: request-termination" in fdid and "status_code: 403" in fdid
    assert "konghq.com/plugins: fdid-deny" in fdid and "fdid-deny" not in out
    # dev: no Front Door, Kong serves HTTPS itself.
    dev = render_platform("kong", "kong", "kong-values.yaml", "kong", "-f", str(PLATFORM / "kong-values-dev.yaml"))
    assert "kong-proxy-tls" in dev or "443" in dev
    assert 'global: "true"' in out and "plugin: rate-limiting" in out
    assert "openid-connect" not in out
    assert "istio.io/rev: asm-1-29" in out


def test_vault_raft_key_vault_unseal_injector():
    out = render_platform(
        "vault", "vault", "vault-values.yaml", "vault",
        "--set-string", r"server.serviceAccount.annotations.azure\.workload\.identity/client-id=cid-vault",
        "--set-string", "server.extraEnvironmentVars.VAULT_AZUREKEYVAULT_VAULT_NAME=kv-corportal-poc01",
    )
    assert "kind: StatefulSet" in out and "-dev" not in out  # never dev mode
    assert 'storage "raft"' in out and 'seal "azurekeyvault"' in out
    assert '"kv-corportal-poc01"' in out and '"vault-unseal"' in out
    assert "azure.workload.identity/client-id: cid-vault" in out
    assert 'azure.workload.identity/use: "true"' in out
    assert "kind: MutatingWebhookConfiguration" in out  # the Agent injector
    assert "LoadBalancer" not in out and "kind: Ingress" not in out  # never public


def test_monitoring_grafana_dashboard_and_federation():
    primary = render_platform(
        "monitoring", "kube-prometheus-stack", "monitoring-values.yaml", "monitoring",
        "--set-string", "corportal.region=westus3",
        "--set-string", "corportal.federateTarget=10.20.0.50:9090",
        "--set-file", f"grafana.dashboards.corportal.rps-by-region.json={PLATFORM / 'dashboards' / 'rps-by-region.json'}",
    )
    scrape = next(
        base64.b64decode(line.split(":", 1)[1].strip().strip('"')).decode()
        for line in primary.splitlines() if "additional-scrape-configs.yaml:" in line
    )
    assert "istio_requests_total" in scrape and 'replacement: "westus3"' in scrape
    assert "/federate" in scrape and '"10.20.0.50:9090"' in scrape
    assert "Requests per second by region" in primary and "sum by (region)" in primary
    assert "existingSecret" not in primary and "name: grafana-admin" in primary
    assert "LoadBalancer" not in primary and "kind: Ingress" not in primary  # port-forward only
    assert "kind: Alertmanager" not in primary

    secondary = render_platform(
        "monitoring", "kube-prometheus-stack", "monitoring-values.yaml", "monitoring",
        "--set-string", "corportal.region=northcentralus",
        "--set", "grafana.enabled=false", "--set", "prometheus.service.type=LoadBalancer",
    )
    assert 'azure-load-balancer-internal: "true"' in secondary and 'type: "LoadBalancer"' in secondary
    assert "monitoring-grafana" not in secondary
