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
