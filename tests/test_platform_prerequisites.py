"""Tests for scripts/platform-prerequisites.py: what is copied, and the name clash."""

import importlib.util
import pathlib

import pytest
import yaml

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "platform-prerequisites.py"
spec = importlib.util.spec_from_file_location("platform_prerequisites", SCRIPT)
prerequisites = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prerequisites)

CRD = {"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition"}
POLICY = {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "ValidatingAdmissionPolicy"}
BINDING = {
    "apiVersion": "admissionregistration.k8s.io/v1",
    "kind": "ValidatingAdmissionPolicyBinding",
}
WEBHOOK = {
    "apiVersion": "admissionregistration.k8s.io/v1",
    "kind": "ValidatingWebhookConfiguration",
}
NAMESPACE = {"apiVersion": "v1", "kind": "Namespace"}
DEPLOYMENT = {"apiVersion": "apps/v1", "kind": "Deployment"}
POLICY_NAMED_LIKE_A_NAMESPACE = {"apiVersion": "cilium.io/v2", "kind": "Namespace"}


def write(path, objects):
    path.write_text(yaml.safe_dump_all(objects))


def read(path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def test_keeps_only_crds_policies_and_namespaces():
    kept = prerequisites.prerequisites(
        "security",
        [CRD, POLICY, BINDING, WEBHOOK, NAMESPACE, DEPLOYMENT, POLICY_NAMED_LIKE_A_NAMESPACE],
    )
    assert kept == [CRD, POLICY, BINDING, NAMESPACE]


def test_operator_crds_are_copied_whole():
    assert prerequisites.prerequisites("cilium.operator-crds", [CRD, DEPLOYMENT]) == [
        CRD,
        DEPLOYMENT,
    ]


def test_main_copies_per_application(tmp_path):
    platform, target = tmp_path / "platform", tmp_path / "dry-run"
    platform.mkdir()
    target.mkdir()
    write(platform / "security.yaml", [POLICY, DEPLOYMENT])
    write(platform / "loki.yaml", [DEPLOYMENT])
    write(platform / "platform.yaml", [NAMESPACE])
    write(target / "umami.yaml", [DEPLOYMENT])
    assert prerequisites.main(["x", str(platform), str(target)]) == 0
    assert sorted(p.name for p in target.iterdir()) == ["security.yaml", "umami.yaml"]
    assert read(target / "security.yaml") == [POLICY]


def test_main_refuses_an_application_name_in_both(tmp_path):
    platform, target = tmp_path / "platform", tmp_path / "dry-run"
    platform.mkdir()
    target.mkdir()
    write(platform / "umami.yaml", [NAMESPACE])
    write(target / "umami.yaml", [DEPLOYMENT])
    with pytest.raises(SystemExit, match="umami is an Application in both"):
        prerequisites.main(["x", str(platform), str(target)])
