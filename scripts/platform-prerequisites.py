#!/usr/bin/env python3
"""Add the platform objects a workload is judged by to a server dry run's input.

    platform-prerequisites.py <platform-render> <dry-run-dir>

<platform-render> is what the homelab repository's `render-charts.py --out`
writes; <dry-run-dir> already holds this repository's render. From each
platform Application this copies only what the homelab `server-dry-run.py`
applies for real: CRDs (and the `<app>.operator-crds.yaml` files whole),
admission policies and their bindings, and Namespaces. The rest of the
platform is the homelab repository's own dry run to judge, so a workload
pull request fails only for what it renders.

Each platform Application keeps its file name, which is the Application
name in the tracking id the admission policies read, so an Application name
both repositories use is refused rather than merged.
"""

import pathlib
import sys

import yaml

PREREQUISITES = {
    ("apiextensions.k8s.io", "CustomResourceDefinition"),
    ("admissionregistration.k8s.io", "ValidatingAdmissionPolicy"),
    ("admissionregistration.k8s.io", "ValidatingAdmissionPolicyBinding"),
    ("admissionregistration.k8s.io", "MutatingAdmissionPolicy"),
    ("admissionregistration.k8s.io", "MutatingAdmissionPolicyBinding"),
    ("", "Namespace"),
}
# The Application objects the platform ApplicationSet generates; not applied.
SKIPPED = {"platform"}
OPERATOR_SUFFIX = ".operator-crds"


def group_of(obj):
    api = obj.get("apiVersion", "")
    return api.rpartition("/")[0] if "/" in api else ""


def prerequisites(entry, objects):
    """The objects of one platform render file the dry run needs."""
    if entry.endswith(OPERATOR_SUFFIX):
        return objects
    return [obj for obj in objects if (group_of(obj), obj["kind"]) in PREREQUISITES]


def main(argv):
    if len(argv) != 3:
        raise SystemExit(__doc__.split("\n\n")[1])
    platform, target = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    copied = 0
    for path in sorted(platform.glob("*.yaml")):
        if path.stem in SKIPPED:
            continue
        objects = [doc for doc in yaml.safe_load_all(path.read_text()) if doc]
        kept = prerequisites(path.stem, objects)
        if not kept:
            continue
        out = target / path.name
        if out.exists():
            raise SystemExit(f"{path.stem} is an Application in both repositories")
        out.write_text(yaml.safe_dump_all(kept, sort_keys=False))
        copied += len(kept)
        print(f"{path.stem}: {len(kept)} of {len(objects)} objects")
    print(f"{copied} platform objects added to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
