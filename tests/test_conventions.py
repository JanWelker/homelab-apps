"""The documented conventions, checked against what ArgoCD will apply.

The Application checks read the `*/application.yaml` files. The rest read
the output of `make dry-run-input`: this repository's render from
$RENDERED_DIR (default output/rendered) and the platform's from
$PLATFORM_RENDERED_DIR (default output/platform), for the bindings it grants
workload ServiceAccounts. They skip when a render is missing; the Server
Dry Run workflow renders both and runs this file.

Each assertion names the page that documents its rule. An exception is an
ALLOWED entry with its reason; an entry nothing matches any more fails too,
so the list cannot rot.
"""

import os
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONVENTIONS = "https://homelab-apps.wlkr.ch/conventions/"
DOCS = "https://homelab.wlkr.ch"
RENDERED = pathlib.Path(os.environ.get("RENDERED_DIR", ROOT / "output" / "rendered"))
PLATFORM = pathlib.Path(os.environ.get("PLATFORM_RENDERED_DIR", ROOT / "output" / "platform"))

WAVE = "argocd.argoproj.io/sync-wave"
SYNC_OPTIONS = "argocd.argoproj.io/sync-options"
WORKLOADS = {"Pod", "Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob"}
PSA_LEVELS = ["privileged", "baseline", "restricted"]
SECURITY_HEADERS = {
    "strict-transport-security": None,
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
}
AGENT_CHART = (
    "the agent-mooring chart renders it with no value to change it; JanWelker/agent-mooring"
)
SOMUCH_CHART = "the chart renders it with no value to change it; somuch-cloud, as #231 noted"
SESSIONS = ("homelab", "sitzplan", "virgil")
SEED_REDIRECT = "the /seed rule only redirects; the page rule sets the headers"

# Exceptions, by the identifier each check prints, with the reason.
ALLOWED = {
    "policy-wave": {
        f"claude-{s}: CiliumNetworkPolicy claude-{s}/claude-{s}": AGENT_CHART for s in SESSIONS
    },
    "probe-entities": {
        **{f"claude-{s}: CiliumNetworkPolicy claude-{s}/claude-{s}": AGENT_CHART for s in SESSIONS},
        "shot-bridge: CiliumNetworkPolicy shot-bridge/shot-bridge": SOMUCH_CHART,
    },
    "dns-rules": {
        **{f"claude-{s}: CiliumNetworkPolicy claude-{s}/claude-{s}": AGENT_CHART for s in SESSIONS},
        "extractor-admin: CiliumNetworkPolicy extractor-admin/extractor-admin": SOMUCH_CHART,
        "shot-bridge: CiliumNetworkPolicy shot-bridge/shot-bridge": SOMUCH_CHART,
    },
    "cpu-limits": {},
    "automount": {},
    "job-limits": {},
    "priority-class": {},
    "route-parents": {},
    "route-matches": {},
    "route-headers": {
        f"{site}-wollbi: HTTPRoute {site}-wollbi/{site}-wollbi rule 0: set"
        " strict-transport-security, set x-content-type-options, set x-frame-options": SEED_REDIRECT
        for site in ("advent", "fest")
    },
    "namespace-policies": {},
}


def documented(violations, rule, doc):
    """Assert violations are exactly the allowed ones, naming the doc."""
    allowed = ALLOWED[rule]
    unexpected = sorted(set(violations) - set(allowed))
    stale = sorted(set(allowed) - set(violations))
    assert not unexpected, f"{rule}, see {doc}:\n  " + "\n  ".join(unexpected)
    assert not stale, f"{rule}: allowed but no longer found, drop from ALLOWED:\n  " + "\n  ".join(
        stale
    )


def strict(violations, doc):
    """Assert there are no violations of a rule that has no exceptions."""
    assert not violations, f"see {doc}:\n  " + "\n  ".join(violations)


# --- Applications -----------------------------------------------------------


def applications():
    """(directory, Application) for every application.yaml."""
    found = []
    for path in sorted(ROOT.glob("*/application.yaml")):
        docs = [doc for doc in yaml.safe_load_all(path.read_text()) if doc]
        assert len(docs) == 1, f"{path}: one Application per file; see {CONVENTIONS}#structure"
        found.append((path.parent.name, docs[0]))
    return found


def sources(app):
    return app["spec"].get("sources") or [app["spec"]["source"]]


def test_applications_follow_the_structure():
    violations = []
    for directory, app in applications():
        if app["kind"] != "Application" or app["metadata"]["name"] != directory:
            violations.append(f"{directory}: an Application named after its directory")
        if app["spec"].get("project") != "apps":
            violations.append(f"{directory}: project {app['spec'].get('project')}, not apps")
        for source in sources(app):
            if "chart" in source or "homelab-apps" not in source["repoURL"]:
                continue
            if source.get("path") != directory:
                violations.append(f"{directory}: deploys {source.get('path')}, not its directory")
            if (source.get("directory") or {}).get("exclude") != "application.yaml":
                violations.append(f"{directory}: its directory source does not exclude itself")
    strict(violations, f"{CONVENTIONS}#structure and {CONVENTIONS}#1-project-apps")


def test_every_application_has_the_shared_sync_policy():
    expected = {
        "automated": {"prune": True, "selfHeal": True},
        "retry": {
            "limit": 10,
            "backoff": {"duration": "30s", "factor": 2, "maxDuration": "5m"},
        },
        "syncOptions": ["ServerSideApply=true"],
    }
    violations = []
    for directory, app in applications():
        wanted = dict(expected)
        if directory.startswith("claude-"):
            del wanted["syncOptions"]
        if app["spec"].get("syncPolicy") != wanted:
            violations.append(f"{directory}: {app['spec'].get('syncPolicy')}")
    strict(violations, f"{CONVENTIONS}#8-the-shared-syncpolicy")


# --- Rendered objects -------------------------------------------------------


def load(directory, skip_platform_files=False):
    if not directory.is_dir():
        pytest.skip(f"render first: make dry-run-input (no {directory})")
    apps = {}
    for path in sorted(directory.glob("*.yaml")):
        if skip_platform_files and (path.stem == "platform" or ".operator-crds" in path.stem):
            continue
        apps[path.stem] = [doc for doc in yaml.safe_load_all(path.read_text()) if doc]
    return apps


@pytest.fixture(scope="module")
def rendered():
    """{application: objects} from this repository's render."""
    return load(RENDERED)


@pytest.fixture(scope="module")
def platform():
    """{application: objects} from the platform's render."""
    return load(PLATFORM, skip_platform_files=True)


def objects(rendered, *kinds):
    for app, objs in rendered.items():
        for obj in objs:
            if not kinds or obj["kind"] in kinds:
                yield app, obj


def ref(app, obj):
    metadata = obj.get("metadata", {})
    namespace = metadata.get("namespace")
    name = f"{namespace}/{metadata.get('name')}" if namespace else metadata.get("name")
    return f"{app}: {obj['kind']} {name}"


def annotation(obj, key):
    return ((obj.get("metadata") or {}).get("annotations") or {}).get(key)


def wave(obj):
    return int(annotation(obj, WAVE) or 0)


def keeps_on_prune(obj):
    return "Prune=false" in (annotation(obj, SYNC_OPTIONS) or "").split(",")


def pod_spec(obj):
    """The pod spec a workload object runs."""
    if obj["kind"] == "Pod":
        return obj.get("spec") or {}
    if obj["kind"] == "CronJob":
        return obj["spec"]["jobTemplate"]["spec"]["template"].get("spec") or {}
    return obj["spec"]["template"].get("spec") or {}


def containers(spec):
    return (spec.get("initContainers") or []) + (spec.get("containers") or [])


def by_namespace(rendered, *kinds):
    found = {}
    for app, obj in objects(rendered, *kinds):
        found.setdefault(obj["metadata"].get("namespace"), []).append((app, obj))
    return found


def test_every_application_owns_its_namespace(rendered):
    destinations = {
        app["metadata"]["name"]: app["spec"]["destination"]["namespace"]
        for _, app in applications()
    }
    namespaces = {
        obj["metadata"]["name"]: (app, obj) for app, obj in objects(rendered, "Namespace")
    }
    violations = []
    for app, namespace in sorted(destinations.items()):
        if app.startswith("claude-"):
            if namespace in namespaces:
                violations.append(f"{app}: the platform declares {namespace}, not this repository")
            continue
        if namespace not in namespaces:
            violations.append(f"{app}: ships no Namespace {namespace}")
            continue
        _, obj = namespaces[namespace]
        labels = obj["metadata"].get("labels") or {}
        levels = {
            mode: labels.get(f"pod-security.kubernetes.io/{mode}")
            for mode in ("enforce", "audit", "warn")
        }
        if not all(level in PSA_LEVELS for level in levels.values()):
            violations.append(f"{app}: Pod Security labels {levels}")
            continue
        enforce = PSA_LEVELS.index(levels["enforce"])
        for mode in ("audit", "warn"):
            if PSA_LEVELS.index(levels[mode]) < min(enforce + 1, len(PSA_LEVELS) - 1):
                violations.append(f"{app}: {mode} {levels[mode]} is not stricter than enforce")
        if wave(obj) != -2 or not keeps_on_prune(obj):
            violations.append(f"{app}: Namespace {namespace} wants sync wave -2 and Prune=false")
    strict(violations, f"{CONVENTIONS}#4-own-your-namespace")


def test_volumes_survive_a_prune(rendered):
    violations = [
        ref(app, obj)
        for app, obj in objects(rendered, "PersistentVolumeClaim")
        if not keeps_on_prune(obj)
    ]
    strict(violations, f"{CONVENTIONS}#3-postgresql-is-always-a-cloudnativepg-cluster")


def test_databases_follow_the_contract(rendered):
    stores = {
        (obj["metadata"]["namespace"], obj["metadata"]["name"])
        for _, obj in objects(rendered, "ObjectStore")
    }
    monitored = {obj["metadata"]["namespace"] for _, obj in objects(rendered, "PodMonitor")}
    violations = []
    for app, cluster in objects(rendered, "Cluster"):
        if cluster["apiVersion"].partition("/")[0] != "postgresql.cnpg.io":
            continue
        spec, name, namespace = cluster["spec"], ref(app, cluster), cluster["metadata"]["namespace"]
        if (spec.get("instances") or 1) == 1 and spec.get("enablePDB") is not False:
            violations.append(f"{name}: a single instance sets enablePDB: false")
        if (spec.get("instances") or 1) > 1 and spec.get("primaryUpdateMethod") != "switchover":
            violations.append(f"{name}: replicas want primaryUpdateMethod: switchover")
        if spec.get("smartShutdownTimeout") != 15:
            violations.append(f"{name}: smartShutdownTimeout: 15")
        if "-standard-" not in (spec.get("imageName") or ""):
            violations.append(f"{name}: the standard image")
        if (spec.get("monitoring") or {}).get("enablePodMonitor"):
            violations.append(f"{name}: a PodMonitor, not monitoring.enablePodMonitor")
        if namespace not in monitored:
            violations.append(f"{name}: no PodMonitor in {namespace}")
        if wave(cluster) >= 0 or not keeps_on_prune(cluster):
            violations.append(f"{name}: an earlier sync wave than the application and Prune=false")
        if annotation(cluster, "homelab.wlkr.ch/backup-exempt"):
            continue
        plugins = [p for p in spec.get("plugins") or [] if p.get("isWALArchiver")]
        store = ((plugins or [{}])[0].get("parameters") or {}).get("barmanObjectName")
        if (namespace, store) not in stores:
            violations.append(f"{name}: no backup.yaml ObjectStore {store} beside it")
    strict(violations, f"{CONVENTIONS}#3-postgresql-is-always-a-cloudnativepg-cluster")


# --- Network policies --------------------------------------------------------


def entities(rules, field):
    return [set(rule.get(field) or []) for rule in rules or []]


def test_no_plain_network_policies(rendered):
    violations = [ref(app, obj) for app, obj in objects(rendered, "NetworkPolicy")]
    strict(violations, f"{CONVENTIONS}#5-ship-a-ciliumnetworkpolicy")


def test_network_policies_sync_with_the_namespace(rendered):
    violations = [
        ref(app, obj) for app, obj in objects(rendered, "CiliumNetworkPolicy") if wave(obj) != -2
    ]
    documented(violations, "policy-wave", f"{CONVENTIONS}#5-ship-a-ciliumnetworkpolicy")


def test_probes_come_from_host_and_remote_node(rendered):
    violations = [
        ref(app, obj)
        for app, obj in objects(rendered, "CiliumNetworkPolicy")
        for found in entities(obj["spec"].get("ingress"), "fromEntities")
        if "host" in found and "remote-node" not in found
    ]
    documented(violations, "probe-entities", f"{CONVENTIONS}#5-ship-a-ciliumnetworkpolicy")


def test_no_dns_rules(rendered):
    violations = sorted(
        {
            ref(app, obj)
            for app, obj in objects(rendered, "CiliumNetworkPolicy")
            for rule in obj["spec"].get("egress") or []
            for to_ports in rule.get("toPorts") or []
            if (to_ports.get("rules") or {}).get("dns")
            or any(str(p.get("port")) == "53" for p in to_ports.get("ports") or [])
        }
    )
    documented(violations, "dns-rules", f"{CONVENTIONS}#5-ship-a-ciliumnetworkpolicy")


def test_every_namespace_with_pods_is_default_deny(rendered):
    policies = {
        (obj["metadata"]["namespace"], obj["metadata"]["name"]): obj
        for _, obj in objects(rendered, "CiliumNetworkPolicy")
    }
    violations = []
    for namespace in sorted(by_namespace(rendered, *WORKLOADS, "Cluster")):
        ingress = policies.get((namespace, "default-ingress"))
        egress = policies.get((namespace, "default-egress"))
        if not ingress or not egress:
            violations.append(f"{namespace}: default-ingress and default-egress")
            continue
        rules = ingress["spec"].get("ingress") or []
        if ingress["spec"].get("endpointSelector") != {} or not (
            {"host", "remote-node"} in entities(rules, "fromEntities")
            and [{}] in [rule.get("fromEndpoints") for rule in rules]
        ):
            violations.append(f"{namespace}: default-ingress admits the namespace and the probes")
        if egress["spec"].get("endpointSelector") != {} or [{}] not in [
            rule.get("toEndpoints") for rule in egress["spec"].get("egress") or []
        ]:
            violations.append(f"{namespace}: default-egress admits the namespace")
    documented(
        violations,
        "namespace-policies",
        f"{CONVENTIONS}#5-ship-a-ciliumnetworkpolicy and "
        f"{DOCS}/platform/security-policies/#network-policies",
    )


def test_the_operator_reaches_every_database(rendered):
    violations = []
    policies = by_namespace(rendered, "CiliumNetworkPolicy")
    for app, cluster in objects(rendered, "Cluster"):
        namespace = cluster["metadata"]["namespace"]
        admitted = any(
            (endpoint.get("matchLabels") or {}).get("k8s:io.kubernetes.pod.namespace")
            == "cnpg-system"
            and any(
                str(port.get("port")) == "8000"
                for to_ports in rule.get("toPorts") or []
                for port in to_ports.get("ports") or []
            )
            for _, policy in policies.get(namespace, [])
            for rule in policy["spec"].get("ingress") or []
            for endpoint in rule.get("fromEndpoints") or []
        )
        if not admitted:
            violations.append(f"{ref(app, cluster)}: cnpg-system on 8000")
    strict(violations, f"{CONVENTIONS}#sync-stuck-on-the-database")


# --- Secrets -----------------------------------------------------------------


def remote_keys(secret):
    spec = secret["spec"]
    keys = [d["remoteRef"].get("key") for d in spec.get("data") or [] if "remoteRef" in d]
    keys += [
        (d.get("match") or {}).get("remoteRef", {}).get("remoteKey")
        for d in spec.get("data") or []
        if "match" in d
    ]
    keys += [
        (d.get("extract") or d.get("find") or {}).get("key") for d in spec.get("dataFrom") or []
    ]
    return [key for key in keys if key]


def stores(secret):
    spec = secret["spec"]
    refs = [spec["secretStoreRef"]] if "secretStoreRef" in spec else spec.get("secretStoreRefs")
    return [(r.get("kind"), r.get("name")) for r in refs or []]


def test_secrets_come_from_the_namespace_path_in_openbao(rendered):
    violations = []
    accounts = {
        obj["metadata"]["namespace"]: obj
        for _, obj in objects(rendered, "ServiceAccount")
        if obj["metadata"]["name"] == "external-secrets-vault"
    }
    for app, secret in objects(rendered, "ExternalSecret", "PushSecret"):
        name, namespace = ref(app, secret), secret["metadata"]["namespace"]
        if stores(secret) != [("ClusterSecretStore", "openbao-apps")]:
            violations.append(f"{name}: names {stores(secret)}, not the openbao-apps store")
        violations += [
            f"{name}: reads {key}, outside {namespace}/"
            for key in remote_keys(secret)
            if not key.startswith(f"{namespace}/")
        ]
        if secret["kind"] == "PushSecret" and wave(secret) != -2:
            violations.append(f"{name}: sync wave -2, ahead of the ExternalSecret")
        if secret["kind"] == "ExternalSecret" and wave(secret) <= -2:
            violations.append(f"{name}: a later sync wave than the generated values at -2")
        account = accounts.get(namespace)
        if not account or wave(account) != -2 or account.get("automountServiceAccountToken"):
            violations.append(f"{name}: no external-secrets-vault ServiceAccount at -2 in it")
    violations += [
        f"{ref(app, obj)}: sync wave -2, with its PushSecret"
        for app, obj in objects(rendered, "Password", "UUID")
        if wave(obj) != -2
    ]
    strict(sorted(set(violations)), f"{CONVENTIONS}#7-real-secrets-come-from-openbao")


# --- Routes ------------------------------------------------------------------


def test_route_parents_are_spelled_out(rendered):
    violations = []
    for app, route in objects(rendered, "HTTPRoute", "TLSRoute"):
        for parent in route["spec"].get("parentRefs") or []:
            missing = [
                field
                for field, value in (
                    ("group", "gateway.networking.k8s.io"),
                    ("kind", "Gateway"),
                    ("sectionName", None),
                )
                if field not in parent or (value and parent[field] != value)
            ]
            if missing:
                violations.append(f"{ref(app, route)} parent {parent['name']}: {missing}")
    documented(violations, "route-parents", f"{CONVENTIONS}#writing-an-httproute")


def test_every_rule_matches_once_a_route_has_several(rendered):
    violations = [
        f"{ref(app, route)} rule {index}"
        for app, route in objects(rendered, "HTTPRoute")
        if len(route["spec"].get("rules") or []) > 1
        for index, rule in enumerate(route["spec"]["rules"])
        if not rule.get("matches")
    ]
    documented(violations, "route-matches", f"{CONVENTIONS}#writing-an-httproute")


def header_problems(rule):
    """What the rule's ResponseHeaderModifier lacks of the three security headers."""
    modifiers = [
        f.get("responseHeaderModifier") or {}
        for f in rule.get("filters") or []
        if f.get("type") == "ResponseHeaderModifier"
    ]
    set_headers = {
        h["name"].lower(): str(h.get("value", "")) for m in modifiers for h in m.get("set") or []
    }
    problems = []
    for name, value in SECURITY_HEADERS.items():
        if name not in set_headers:
            problems.append(f"set {name}")
        elif value and set_headers[name] != value:
            problems.append(f"{name}: {value}")
    hsts = set_headers.get("strict-transport-security", "").lower()
    if "includesubdomains" in hsts or "preload" in hsts:
        problems.append("HSTS without includeSubDomains or preload")
    return problems


def test_routes_set_the_security_headers(rendered):
    violations = [
        f"{ref(app, route)} rule {index}: {', '.join(problems)}"
        for app, route in objects(rendered, "HTTPRoute")
        for index, rule in enumerate(route["spec"].get("rules") or [])
        if (problems := header_problems(rule))
    ]
    documented(violations, "route-headers", f"{CONVENTIONS}#writing-an-httproute")


# --- Pods --------------------------------------------------------------------


def test_jobs_run_at_batch_priority_and_services_at_the_default(rendered):
    violations = []
    for app, obj in objects(rendered, *WORKLOADS):
        priority = pod_spec(obj).get("priorityClassName")
        wanted = "batch" if obj["kind"] in {"Job", "CronJob"} else None
        if priority != wanted:
            violations.append(f"{ref(app, obj)}: {priority}, not {wanted}")
    documented(violations, "priority-class", f"{CONVENTIONS}#what-you-do-not-have-to-write")


def test_no_cpu_limits(rendered):
    violations = [
        f"{ref(app, obj)} {container['name']}"
        for app, obj in objects(rendered, *WORKLOADS)
        for container in containers(pod_spec(obj))
        if "cpu" in ((container.get("resources") or {}).get("limits") or {})
    ]
    documented(violations, "cpu-limits", f"{CONVENTIONS}#9-pods")


def bound_service_accounts(*renders):
    """(namespace, name) of every ServiceAccount a binding names, and bound namespaces."""
    accounts, namespaces = set(), set()
    for render in renders:
        for _, binding in objects(render, "RoleBinding", "ClusterRoleBinding"):
            for subject in binding.get("subjects") or []:
                kind, name = subject.get("kind"), subject.get("name", "")
                if kind == "ServiceAccount":
                    namespace = subject.get("namespace") or binding["metadata"].get("namespace")
                    accounts.add((namespace, name))
                elif kind == "Group" and name in {"system:serviceaccounts", "system:authenticated"}:
                    namespaces.add("*")
                elif kind == "Group" and name.startswith("system:serviceaccounts:"):
                    namespaces.add(name.removeprefix("system:serviceaccounts:"))
    return accounts, namespaces


def test_pods_without_api_access_mount_no_token(rendered, platform):
    accounts = {
        (obj["metadata"]["namespace"], obj["metadata"]["name"]): obj
        for _, obj in objects(rendered, "ServiceAccount")
    }
    bound, bound_namespaces = bound_service_accounts(rendered, platform)
    violations = []
    for app, obj in objects(rendered, *WORKLOADS):
        spec, namespace = pod_spec(obj), obj["metadata"]["namespace"]
        name = spec.get("serviceAccountName") or "default"
        mount = spec.get("automountServiceAccountToken")
        if mount is None:
            mount = (accounts.get((namespace, name)) or {}).get("automountServiceAccountToken")
        if mount is False:
            continue
        if (namespace, name) in bound or {namespace, "*"} & bound_namespaces:
            continue
        violations.append(f"{ref(app, obj)} as {name}")
    documented(violations, "automount", f"{CONVENTIONS}#9-pods")


def test_jobs_end_and_are_cleaned_up(rendered):
    violations = []
    for app, obj in objects(rendered, "Job", "CronJob"):
        spec = obj["spec"]["jobTemplate"]["spec"] if obj["kind"] == "CronJob" else obj["spec"]
        missing = [
            field
            for field in ("activeDeadlineSeconds", "ttlSecondsAfterFinished")
            if not spec.get(field)
        ]
        if missing:
            violations.append(f"{ref(app, obj)}: {missing}")
    documented(violations, "job-limits", f"{CONVENTIONS}#9-pods")
