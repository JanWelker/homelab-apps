#!/usr/bin/env python3
"""Render every chart-based Application the way ArgoCD will.

There is no ArgoCD diff preview on this repository: the tool renders the
repository it is given, and it is pointed at the platform one. This is the
cheap half of what it would have caught. A chart that refuses the values in
an Application fails here rather than on the cluster.

    render-charts.py [--out <dir>] [<glob> ...]

The globs select Applications and default to this repository's layout. With
--out, the rendered manifests are written to <dir>/<application>.yaml for
reading; without it only the exit code and one line per Application remain.
Requires helm on PATH.

One parser, not two: reading chart, repo, version and values out of the YAML
with awk looks simpler until a `- repoURL:` list item shifts the fields by
one and helm is handed the string "repoURL:" as a chart repository, which it
resolves against a same-named directory in the working tree and renders
something that was never asked for.
"""

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

DEFAULT_GLOBS = ("*/application.yaml",)
ACTIONS = "GITHUB_ACTIONS" in os.environ


def chart_sources(app_path):
    spec = yaml.safe_load(app_path.read_text())["spec"]
    return [s for s in (spec.get("sources") or [spec["source"]]) if "chart" in s]


def render(name, source):
    """helm template for one chart source; returns (ok, output)."""
    values = source.get("helm", {}).get("valuesObject", {})
    # From an empty directory: `helm template <name> <chart> --repo <url>`
    # prefers a local directory of that name over the repository, and every
    # chart here is named after a directory that exists.
    with tempfile.TemporaryDirectory() as workdir:
        values_file = pathlib.Path(workdir, "values.yaml")
        values_file.write_text(yaml.safe_dump(values))
        result = subprocess.run(
            ["helm", "template", name, source["chart"],
             "--repo", source["repoURL"],
             "--version", str(source["targetRevision"]),
             "--namespace", name,
             "--values", str(values_file)],
            cwd=workdir, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, result.stdout


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("globs", nargs="*", default=list(DEFAULT_GLOBS))
    args = parser.parse_args(argv[1:])
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    failed = False
    for pattern in args.globs:
        for app in sorted(pathlib.Path(".").glob(pattern)):
            name = app.parent.name
            sources = chart_sources(app)
            if not sources:
                print(f"{name}: plain manifests, nothing to render")
                continue
            for source in sources:
                label = f"{name} ({source['chart']} {source['targetRevision']} from {source['repoURL']})"
                ok, output = render(name, source)
                if ok:
                    print(f"{label}: ok")
                    if args.out:
                        (args.out / f"{name}.yaml").write_text(output)
                else:
                    failed = True
                    prefix = f"::error title={name}::" if ACTIONS else "error: "
                    print(f"{prefix}helm template failed for {label}\n{output}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
