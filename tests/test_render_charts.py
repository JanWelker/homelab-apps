"""Tests for the pure helpers in scripts/render-charts.py; helm is never run."""

import importlib.util
import pathlib

import pytest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "render-charts.py"
spec = importlib.util.spec_from_file_location("render_charts", SCRIPT)
render_charts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_charts)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.2.3", (1, 2, 3)),
        ("v2.10", (2, 10)),
        ("3", (3,)),
        ("1.2.3-rc.1", (1, 2, 3)),
        ("2026.11.1@sha256:abc", (2026, 11, 1)),
        ("latest", None),
        ("", None),
        (None, None),
    ],
)
def test_version_tuple(text, expected):
    assert render_charts.version_tuple(text) == expected


def test_version_tuple_orders_numerically():
    assert render_charts.version_tuple("1.10.0") > render_charts.version_tuple("1.9.9")


def test_chart_args_http_repository():
    source = {"repoURL": "https://charts.example.org", "chart": "app", "targetRevision": "1.2.3"}
    assert render_charts.chart_args(source) == [
        "app",
        "--repo",
        "https://charts.example.org",
        "--version",
        "1.2.3",
    ]


@pytest.mark.parametrize("repo", ["ghcr.io/org/charts", "ghcr.io/org/charts/"])
def test_chart_args_oci_registry(repo):
    source = {"repoURL": repo, "chart": "app", "targetRevision": "0.5.1"}
    assert render_charts.chart_args(source) == [
        "oci://ghcr.io/org/charts/app",
        "--version",
        "0.5.1",
    ]


def test_chart_args_stringifies_revision():
    source = {"repoURL": "https://x.example", "chart": "c", "targetRevision": 2}
    assert render_charts.chart_args(source)[-1] == "2"


def source(tag=None):
    values = {"image": {"tag": tag}} if tag else {}
    return {
        "repoURL": "https://x.example",
        "chart": "c",
        "targetRevision": "1.0.0",
        "helm": {"valuesObject": values},
    }


@pytest.fixture
def helm(monkeypatch):
    """Replace `helm show` with canned chart values and appVersion."""

    def install(values=None, app_version="2.3.4"):
        def fake(what, _source):
            return (values or {}) if what == "values" else {"appVersion": app_version}

        monkeypatch.setattr(render_charts, "helm_show", fake)

    return install


def test_check_tag_without_override_is_fine(helm):
    helm()
    assert render_charts.check_tag(source()) is None


def test_check_tag_chart_with_own_default_is_fine(helm):
    helm(values={"image": {"tag": "9.9.9"}})
    assert render_charts.check_tag(source("1.0.0")) is None


@pytest.mark.parametrize("tag", ["2.3.4", "v2.3.5", "2.4.0@sha256:abc"])
def test_check_tag_in_step(helm, tag):
    helm()
    assert render_charts.check_tag(source(tag)) is None


@pytest.mark.parametrize("tag", ["2.3.3", "3.0.0", "1.9.9"])
def test_check_tag_out_of_step(helm, tag):
    helm()
    problem = render_charts.check_tag(source(tag))
    assert problem is not None
    assert "out of step with appVersion 2.3.4" in problem


def test_check_tag_unparseable(helm):
    helm()
    assert "cannot compare" in render_charts.check_tag(source("latest"))


def test_drop_nulls_as_argocd_stores_values_object():
    values = {"a": None, "b": {"c": None, "d": 1}, "e": [{"f": None}, 2]}
    assert render_charts.drop_nulls(values) == {"b": {"d": 1}, "e": [{}, 2]}


@pytest.mark.parametrize(
    ("name", "pattern", "expected"),
    [
        ("application.yaml", "application.yaml", True),
        ("deployment.yaml", "application.yaml", False),
        ("values.yaml", "{application,values}.yaml", True),
        ("seed-job.yaml", "*-job.yaml", True),
    ],
)
def test_brace_match(name, pattern, expected):
    assert render_charts.brace_match(name, pattern) is expected


def test_load_objects_unpacks_a_list():
    text = "apiVersion: v1\nkind: List\nitems:\n  - {apiVersion: v1, kind: ConfigMap}\n---\n"
    assert render_charts.load_objects(text, "x") == [{"apiVersion": "v1", "kind": "ConfigMap"}]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("apiVersion: v1\nkind: ConfigMap\nkind: Secret\n", "duplicate key 'kind'"),
        ("image:\n  tag: 1.0.0\n", "not a Kubernetes object"),
    ],
)
def test_load_objects_refuses(text, message):
    with pytest.raises(render_charts.RenderError, match=message):
        render_charts.load_objects(text, "x")


@pytest.mark.parametrize(
    ("hook", "expected"),
    [
        ("test", True),
        ("test-success, test-failure", True),
        ("pre-install,test", False),
        ("", False),
    ],
)
def test_is_test_hook(hook, expected):
    obj = {"metadata": {"annotations": {"helm.sh/hook": hook}}}
    assert render_charts.is_test_hook(obj) is expected


def directory_source(**directory):
    return {
        "repoURL": "https://github.com/JanWelker/homelab-apps.git",
        "targetRevision": "HEAD",
        "path": "app",
        "directory": directory,
    }


def test_directory_files_exclude_and_suffix(tmp_path):
    (tmp_path / "app" / "sub").mkdir(parents=True)
    for name in ("application.yaml", "deployment.yaml", "README.md", "sub/job.yaml"):
        (tmp_path / "app" / name).write_text(name)
    files = render_charts.directory_files(directory_source(exclude="application.yaml"), tmp_path)
    assert files == [("deployment.yaml", "deployment.yaml")]
    recursed = render_charts.directory_files(directory_source(recurse=True), tmp_path)
    assert [name for name, _ in recursed] == ["application.yaml", "deployment.yaml", "sub/job.yaml"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"repoURL": "https://github.com/example/other.git"}, "only this repository"),
        ({"kustomize": {}}, r"unsupported source fields \['kustomize'\]"),
        ({"directory": {"jsonnet": {}}}, r"unsupported source fields \['jsonnet'\]"),
        ({"path": "missing"}, "is not a directory"),
    ],
)
def test_directory_files_refuses(tmp_path, change, message):
    (tmp_path / "app").mkdir()
    with pytest.raises(render_charts.RenderError, match=message):
        render_charts.directory_files({**directory_source(), **change}, tmp_path)


def test_render_refuses_unsupported_helm_fields():
    source = {"repoURL": "https://x.example", "chart": "c", "targetRevision": "1", "helm": {}}
    source["helm"]["valueFiles"] = ["$values/x.yaml"]
    ok, output = render_charts.render({"metadata": {"name": "a"}, "spec": {}}, source)
    assert not ok
    assert "valueFiles" in output


def test_set_namespaces_defaults_only_namespaced_objects():
    app = {"spec": {"destination": {"namespace": "umami"}}}
    crd = {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {"name": "things.example.com"},
        "spec": {"group": "example.com", "names": {"kind": "Thing"}, "scope": "Cluster"},
    }
    objects = [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "a"}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "b", "namespace": "x"}},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole", "metadata": {}},
        {"apiVersion": "example.com/v1", "kind": "Thing", "metadata": {"name": "t"}},
        crd,
    ]
    namespaces = [
        o["metadata"].get("namespace") for o in render_charts.set_namespaces(app, objects)
    ]
    assert namespaces == ["umami", "x", None, None, None]
