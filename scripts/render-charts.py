#!/usr/bin/env python3
"""Render every Application the way ArgoCD will.

There is no ArgoCD diff preview on this repository: the tool renders the
repository it is given, and it is pointed at the platform one. This is the
cheap half of what it would have caught. A chart that refuses the values in
an Application, or a manifest that does not parse, fails here rather than on
the cluster.

It also holds an `image.tag` override to the chart it overrides. Where the
chart derives its tag from `appVersion`, a pinned tag stops following it, so
a chart bump would leave the pod on the old release. The pinned version
must share the chart's major and must not be older than `appVersion`.

    render-charts.py [--out <dir>] [<glob> ...]

The globs select Applications and default to this repository's layout. With
--out, everything an Application deploys is written to <dir>/<application>.yaml,
named after the Application; the Server Dry Run workflow sends that to an API
server. Without it only the exit code and one line per source remain.
Requires helm on PATH.

The source shapes this repository uses are rendered as ArgoCD does: a Helm
chart with `valuesObject` (null values dropped, as ArgoCD loses them when it
stores the field as JSON; CRDs included; Helm test hooks left out, as ArgoCD
never applies them), and a `directory` source in this repository (`recurse`,
`include`, `exclude`). A namespaced object without a namespace gets the
destination's. Any other shape fails, so a new one is added here before it
is used rather than silently rendering nothing. A duplicate mapping key fails
too: the API server rejects it, while a YAML library keeps the last value.

One parser, not two: reading chart, repo, version and values out of the YAML
with awk looks simpler until a `- repoURL:` list item shifts the fields by
one and helm is handed the string "repoURL:" as a chart repository, which it
resolves against a same-named directory in the working tree and renders
something that was never asked for.
"""

import argparse
import fnmatch
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

DEFAULT_GLOBS = ("*/application.yaml",)
ACTIONS = "GITHUB_ACTIONS" in os.environ
# The repository the Applications name for their own manifests.
SELF_REPO = "github.com/janwelker/homelab-apps"
SOURCE_FIELDS = {"repoURL", "targetRevision", "path", "directory"}
CHART_FIELDS = {"repoURL", "targetRevision", "chart", "helm"}
DIRECTORY_FIELDS = {"recurse", "include", "exclude"}
TEST_HOOKS = {"test", "test-success", "test-failure"}
# Built-in cluster-scoped kinds a chart may render, as (group, kind); its
# own CRDs add theirs.
CLUSTER_SCOPED = {
    ("", "Namespace"),
    ("", "PersistentVolume"),
    ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration"),
    ("apiextensions.k8s.io", "CustomResourceDefinition"),
    ("rbac.authorization.k8s.io", "ClusterRole"),
    ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("scheduling.k8s.io", "PriorityClass"),
    ("storage.k8s.io", "StorageClass"),
}


class RenderError(Exception):
    """A source that cannot be rendered; the message says why."""


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses a duplicate key, as the API server does."""


def _strict_mapping(loader, node):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key != "<<" and key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _strict_mapping)


def sources_of(app):
    spec = app["spec"]
    return spec.get("sources") or [spec["source"]]


def chart_args(source):
    """The chart reference and version flags helm takes for one source.

    A repoURL with an http(s) scheme is a chart repository, so the chart is
    its name plus --repo. Anything else is an OCI registry path (ArgoCD
    takes it without a scheme), which helm wants as oci://<repoURL>/<chart>.
    """
    version = ["--version", str(source["targetRevision"])]
    if source["repoURL"].startswith(("http://", "https://")):
        return [source["chart"], "--repo", source["repoURL"], *version]
    return [f"oci://{source['repoURL'].rstrip('/')}/{source['chart']}", *version]


def helm_show(what, source):
    """`helm show chart|values` for one source, parsed; from an empty directory as in render()."""
    with tempfile.TemporaryDirectory() as workdir:
        result = subprocess.run(
            ["helm", "show", what, *chart_args(source)],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=True,
        )
    return yaml.safe_load(result.stdout) or {}


def version_tuple(text):
    match = re.match(r"v?(\d+(?:\.\d+)*)", str(text))
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def check_tag(source):
    """None if the source's image.tag override is in step with the chart, else why not."""
    image = source.get("helm", {}).get("valuesObject", {}).get("image") or {}
    tag = image.get("tag")
    if not tag:
        return None
    # A chart that ships its own default tag does not tie it to appVersion.
    if (helm_show("values", source).get("image") or {}).get("tag"):
        return None
    app_version = helm_show("chart", source).get("appVersion")
    pinned, expected = version_tuple(tag), version_tuple(app_version)
    if pinned is None or expected is None:
        return f"cannot compare image.tag {tag} with appVersion {app_version}"
    if pinned[0] != expected[0] or pinned < expected:
        return (
            f"image.tag {tag.split('@')[0]} is out of step with appVersion {app_version}; "
            f"set it to the {app_version} tag with its digest in the same pull request"
        )
    return None


def drop_nulls(value):
    """valuesObject as ArgoCD hands it to Helm: without null mapping values."""
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nulls(v) for v in value]
    return value


def load_objects(text, origin):
    """The Kubernetes objects of a YAML stream; a List is unpacked as kubectl does."""
    try:
        docs = [doc for doc in yaml.load_all(text, Loader=StrictLoader) if doc]
    except yaml.YAMLError as error:
        raise RenderError(f"{origin}: {error}") from error
    objects = []
    for doc in docs:
        if not (isinstance(doc, dict) and "apiVersion" in doc and "kind" in doc):
            raise RenderError(f"{origin}: a document that is not a Kubernetes object")
        if doc["kind"].endswith("List") and "items" in doc:
            objects.extend(item for item in doc["items"] or [] if item)
        else:
            objects.append(doc)
    return objects


def is_test_hook(obj):
    """A Helm test hook, which ArgoCD maps to no sync phase and so never applies."""
    hooks = ((obj.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook", "")
    return bool(hooks) and set(re.split(r"\s*,\s*", hooks.strip())) <= TEST_HOOKS


def render(app, source):
    """helm template for one chart source, as ArgoCD runs it; returns (ok, output)."""
    unsupported = (set(source) - CHART_FIELDS) | (set(source.get("helm") or {}) - {"valuesObject"})
    if unsupported:
        return False, f"unsupported source fields {sorted(unsupported)}"
    values = drop_nulls(source.get("helm", {}).get("valuesObject", {}))
    namespace = app["spec"]["destination"].get("namespace") or "default"
    # From an empty directory: `helm template <name> <chart> --repo <url>`
    # prefers a local directory of that name over the repository, and every
    # chart here is named after a directory that exists.
    with tempfile.TemporaryDirectory() as workdir:
        values_file = pathlib.Path(workdir, "values.yaml")
        values_file.write_text(yaml.safe_dump(values))
        result = subprocess.run(
            [
                "helm",
                "template",
                app["metadata"]["name"],
                *chart_args(source),
                "--namespace",
                namespace,
                "--include-crds",
                "--values",
                str(values_file),
            ],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, result.stdout


def repo_key(url):
    return re.sub(r"(\.git)?/?$", "", re.sub(r"^https?://", "", url)).lower()


def brace_match(name, pattern):
    """Go glob match as ArgoCD's directory include/exclude uses it, braces included."""
    group = re.search(r"\{([^}]*)\}", pattern)
    if not group:
        return fnmatch.fnmatchcase(name, pattern)
    return any(
        brace_match(name, pattern[: group.start()] + alt + pattern[group.end() :])
        for alt in group.group(1).split(",")
    )


def directory_files(source, root):
    """(relative path, text) of every manifest a directory source in this repository holds."""
    if repo_key(source["repoURL"]) != SELF_REPO:
        raise RenderError(f"{source['repoURL']}: only this repository's directories render here")
    directory = source.get("directory") or {}
    unsupported = (set(source) - SOURCE_FIELDS) | (set(directory) - DIRECTORY_FIELDS)
    if unsupported:
        raise RenderError(f"{source['path']}: unsupported source fields {sorted(unsupported)}")
    base = root / source["path"]
    if not base.is_dir():
        raise RenderError(f"{source['path']} is not a directory")
    files = []
    for file in sorted(base.glob("**/*" if directory.get("recurse") else "*")):
        if file.suffix not in {".yaml", ".yml", ".json"} or not file.is_file():
            continue
        relative = file.relative_to(base).as_posix()
        if directory.get("include") and not brace_match(relative, directory["include"]):
            continue
        if directory.get("exclude") and brace_match(relative, directory["exclude"]):
            continue
        files.append((relative, file.read_text()))
    return files


def group_of(obj):
    api = obj.get("apiVersion", "")
    return api.rpartition("/")[0] if "/" in api else ""


def set_namespaces(app, objects):
    """ArgoCD puts a namespaced object without a namespace into the destination's."""
    namespace = app["spec"]["destination"].get("namespace")
    cluster_scoped = CLUSTER_SCOPED | {
        (obj["spec"]["group"], obj["spec"]["names"]["kind"])
        for obj in objects
        if obj["kind"] == "CustomResourceDefinition" and obj["spec"].get("scope") == "Cluster"
    }
    for obj in objects:
        metadata = obj.setdefault("metadata", {})
        scoped = (group_of(obj), obj["kind"]) not in cluster_scoped
        if namespace and scoped and not metadata.get("namespace"):
            metadata["namespace"] = namespace
    return objects


def report(name, message):
    prefix = f"::error title={name}::" if ACTIONS else "error: "
    print(f"{prefix}{message}", file=sys.stderr)


def render_application(app_path):
    """(name, objects, problems) for one application.yaml."""
    app = yaml.safe_load(app_path.read_text())
    name = app["metadata"]["name"]
    objects, problems = [], []
    for source in sources_of(app):
        if "chart" not in source:
            try:
                for relative, text in directory_files(source, pathlib.Path(".")):
                    objects += load_objects(text, f"{source['path']}/{relative}")
                print(f"{name} ({source['path']}): ok")
            except RenderError as error:
                problems.append(str(error))
            continue
        label = f"{name} ({source['chart']} {source['targetRevision']} from {source['repoURL']})"
        ok, output = render(app, source)
        if ok:
            try:
                objects += [o for o in load_objects(output, label) if not is_test_hook(o)]
                print(f"{label}: ok")
            except RenderError as error:
                ok, output = False, str(error)
        if not ok:
            problems.append(f"helm template failed for {label}\n{output}")
        try:
            problem = ok and check_tag(source)
        except subprocess.CalledProcessError as error:
            problem = f"helm show failed: {error.stderr.strip()}"
        if problem:
            problems.append(f"{label}: {problem}")
    return name, set_namespaces(app, objects), problems


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("globs", nargs="*", default=list(DEFAULT_GLOBS))
    args = parser.parse_args(argv[1:])
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    failed = False
    for pattern in args.globs:
        for app_path in sorted(pathlib.Path(".").glob(pattern)):
            name, objects, problems = render_application(app_path)
            for problem in problems:
                failed = True
                report(name, problem)
            if args.out and not problems:
                (args.out / f"{name}.yaml").write_text(yaml.safe_dump_all(objects, sort_keys=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
