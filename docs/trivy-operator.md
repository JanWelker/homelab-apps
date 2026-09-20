---
description: "Continuous vulnerability, misconfiguration, secret, RBAC and CIS compliance scanning, and why every finding is a CRD rather than a row in a database."
---

# Trivy Operator

Aqua Security's [Trivy Operator](https://aquasecurity.github.io/trivy-operator/latest/)
scans everything the cluster runs — container images for CVEs, workloads for
misconfiguration, images for committed credentials, roles for excessive
permissions, and the nodes themselves against CIS — and writes every result back
into the cluster as a Kubernetes object.

It replaced Kubescape, which was removed from the platform repository. The two
overlap almost completely in what they check; what decided it is below.

## At a glance

| | |
| --- | --- |
| Namespace | `trivy-system` |
| Chart | `trivy-operator`, from `aquasecurity.github.io/helm-charts` |
| Project | `apps` |
| URL | None. It has no user interface at all |
| Dashboard | [Trivy Operator](https://monitoring.infra.k8s.wlkr.ch/d/trivy-operator-overview) |
| Database | None — see [Reports are CRDs](#reports-are-crds) |
| Storage | 5Gi `rook-ceph-block`, for the Trivy server's vulnerability database |
| Depends on | Monitoring (the `ServiceMonitor`), Rook-Ceph (the PVC) |

## What it scans

Six scanners, all enabled. Each writes its own kind of report:

| Scanner | Produces | Answers |
| --- | --- | --- |
| Vulnerability | `VulnerabilityReport` | Which CVEs are in the images we run |
| Exposed secret | `ExposedSecretReport` | Which images have credentials baked in |
| Config audit | `ConfigAuditReport` | Which workloads are misconfigured |
| RBAC assessment | `RbacAssessmentReport` | Which roles grant too much |
| Infra assessment | `InfraAssessmentReport` | Whether the nodes pass CIS |
| Compliance | `ClusterComplianceReport` | CIS 1.23, NSA/CISA 1.0, PSS baseline and restricted |

The compliance specs are the four the chart ships that apply to a kubeadm
cluster. The `eks-` and `rke2-` specs are for other distributions and are left
out rather than reported as failing.

## Reports are CRDs

There is no database here, and that is not an omission. Trivy Operator's only
storage backend is the Kubernetes API: every finding is a custom resource in the
namespace of the workload it describes. The one alternative the chart offers —
`alternateReportStorage` — writes the same objects as JSON files onto a PVC, and
is meant for clusters whose etcd cannot take the volume. Neither option is
PostgreSQL, so the repository's [CloudNativePG
rule](conventions.md#3-postgresql-is-always-a-cloudnativepg-cluster) does not
apply: there is no database to move out of a chart.

What that does mean is that reports cost etcd space, and they are bounded
deliberately:

- `scannerReportTTL: 24h` — a report older than a day is deleted and rebuilt.
  Reports are derived from the cluster, so a stale one is worse than a missing
  one.
- `scanOnlyCurrentRevisions` — only the live ReplicaSet of a Deployment is
  scanned, not every superseded one.
- `scanJobTTL: 10m` — finished scan jobs and their secrets do not accumulate.

## One Trivy server, not one download per scan

`builtInTrivyServer: true` puts the operator into `ClientServer` mode: a single
`trivy-server` StatefulSet holds the vulnerability database on a 5Gi
`rook-ceph-block` PVC, and scan jobs query it over `trivy-service:4954` instead
of each fetching the database for itself.

Standalone mode is the chart's default and it works, but every scan job then
downloads several hundred megabytes of `trivy-db` and `trivy-java-db`. Across
six nodes and every workload in the cluster that is both a lot of egress and a
good way to meet a registry rate limit — which a scanner reports as zero
findings, not as an error.

## Unfixed vulnerabilities stay in the report

`ignoreUnfixed` is left `false`, against the recommendation in Aqua's own
Grafana tutorial. A finding with no available fix is not noise: it is usually
the signal that a **base image** is the wrong one, and dropping those hides the
single most actionable class of result. Severity is likewise unfiltered —
`UNKNOWN` through `CRITICAL` — because a finding the scanner could not grade is
exactly the one worth reading.

`additionalVulnerabilityReportFields` adds the CVSS score, target, class and
package path to each entry, so a report can be triaged without going back to
the registry to work out what a package even is. It does **not** add the
description or the links, for the reason below.

## A report too large to store is a report that never appears

Every `VulnerabilityReport` is an ordinary object written through the API
server, so it is subject to the 2 MiB gRPC write ceiling. Exceed it and the
write is rejected:

```text
rpc error: code = ResourceExhausted desc =
trying to send message larger than max (2601323 vs. 2097152)
```

That line in the operator log is the **only** evidence. No report is created,
no partial object, no event on the workload. A workload with no report looks
exactly like a workload nobody asked about, and an empty dashboard row reads
the same whether an image is clean or was never scanned at all.

It is not hypothetical. Nextcloud and Authentik -- the two most exposed
applications here -- silently had no vulnerability data whatsoever, while their
`ConfigAuditReports` existed and made them look covered.

`Description` and `Links` were the cause. Measured across the reports that did
store:

| fields | all reports | largest one |
| ------ | ----------- | ----------- |
| with `Description,Links` | 17.8 MB | 1.07 MB |
| without `Links` | 8.1 MB | 0.57 MB |
| without either | 4.8 MB | 0.35 MB |

`Links` alone is 55% of the payload -- it is a long list of URLs per finding.
Dropping both leaves 27% of the original, which puts the 2.60 MB report that
failed at roughly 0.7 MB.

The trade is worth naming rather than hiding. The description is the field that
most helps judge whether a finding is *reachable* -- it is why a CoreDNS CVE
could be dismissed as DoH-only without leaving the cluster. But it is one
lookup away from any CVE ID, whereas an absent report tells you nothing at all.
Availability of the data beats richness of the data.

!!! warning "The ceiling is closer than it looks"
    The largest report that still stored was 1.07 MB against a 2 MiB limit --
    half the budget, before this change. Findings only accumulate, so the next
    image to cross the line does so in silence too.

Which means the count of reports is not a check. Reconcile running images
against scanned ones instead, and treat a difference as a missing scan until
proven otherwise:

```bash
kubectl get pods -A -o json \
  | jq -r '.items[].spec.containers[].image' | sort -u | wc -l
kubectl get vulnerabilityreports -A -o json \
  | jq -r '.items[].report.artifact.repository' | sort -u | wc -l
```

## Metrics, and the one that is switched off

The operator exports counts per severity per workload, plus a per-finding
"info" series for each scanner. All of those are on, and the dashboard's tables
are built on them.

`metricsVulnIdEnabled` is the exception and is deliberately **off**. It emits
one series per CVE per container, labelled with the package, version, score and
publication date. On a cluster this size that is a six-figure series count on
its own, and every one of those labels is already in the `VulnerabilityReport`
that the metric was derived from. `kubectl` is the right tool for that question.

!!! warning "`reportType: summary`, or the compliance metric disappears"
    The collector skips any `ClusterComplianceReport` whose format is `all`,
    so setting the intuitive-looking `compliance.reportType: all` silently
    stops `trivy_compliance_info` being emitted and empties the dashboard's
    failing-controls table. `summary` keeps the metric; the per-control detail
    is still in the report object either way. The `status` label on both
    compliance metrics is title-cased — `Fail` and `Pass`, not `FAIL`.

## On the control plane too

Both `nodeCollector.tolerations` and `trivyOperator.scanJobTolerations` carry
the `node-role.kubernetes.io/control-plane` toleration. Without it,
node-collector never lands on `loki`, `odin` or `thor`, and the CIS infra
assessment silently covers only the three worker nodes — reporting a clean
result for a control plane it never looked at.

node-collector is also why the namespace runs at `privileged`: it hostPath-mounts
`/var/lib/etcd`, `/var/lib/kubelet`, `/etc/kubernetes` and `/etc/cni/net.d` to
read the file modes and flags those checks are about, and `baseline` forbids
hostPath outright. The scan jobs themselves are not privileged — the chart gives
them `drop: [ALL]`, no privilege escalation and a read-only root filesystem —
and `audit`/`warn` stay at `restricted` so that stays visible.

## Reading results without Grafana

The dashboard is a summary; the objects have the detail.

```bash
# What has been scanned, worst first
kubectl get vulnerabilityreports -A --sort-by='.report.summary.criticalCount'

# The findings themselves, for one workload
kubectl get vulnerabilityreports -n <ns> <name> -o json \
  | jq '.report.vulnerabilities[]
        | select(.severity=="CRITICAL")
        | {id: .vulnerabilityID, pkg: .resource,
           installed: .installedVersion, fixed: .fixedVersion}'

# Misconfiguration, RBAC and node checks
kubectl get configauditreports -A
kubectl get rbacassessmentreports,clusterrbacassessmentreports -A
kubectl get infraassessmentreports -A

# Which compliance controls are failing
kubectl get clustercompliancereports k8s-cis-1.23 -o json \
  | jq '.status.summary, (.status.summaryReport.controlCheck[]
        | select(.totalFail > 0))'
```

!!! danger "Zero is not the same as clean"
    A report that reads zero may be a clean image or a scan that failed — a
    rate-limited registry pull, a timeout, an image the operator could not
    resolve. Check the object exists and carries a real digest before believing
    a zero, and look at `kubectl -n trivy-system get jobs` when one never
    appears at all. This is the failure mode the
    [vulnerability-triage](https://github.com/JanWelker/homelab) skill opens
    with, and it costs a triage pass every time it is forgotten.

## Why it replaced Kubescape

Kubescape covered the same ground and was removed rather than run alongside.
What actually decided it:

- **The scan pipeline was fragile in ways that were invisible.** An image whose
  SBOM exceeded a size ceiling was not scanned at all and reported zero
  findings; raising the ceiling did not help, because the operator lacked the
  RBAC to delete the oversized SBOM it had already stored, so the too-large
  record was never replaced.
- **Results lived behind an aggregated API server** backed by its own PVC, which
  made "is this number real" a question about the storage layer rather than
  about the image.
- **The scanner image had to be pinned ahead of the chart** to work around
  scheduled scans that failed outright in the version the chart shipped.

Trivy Operator keeps its reports in ordinary CRDs, ships no aggregated API
server, and its scanner is the same Trivy already familiar from CI. What is
genuinely lost is **relevancy** — Kubescape's eBPF node-agent could mark a
finding as relevant when the vulnerable binary was actually loaded at runtime,
and Trivy Operator has no equivalent. Reachability is now an argument to be made
from the workload's configuration rather than a column to sort on.

The runtime-detection half of Kubescape — the eBPF sensor, network-policy
generation and seccomp profiling — has no replacement here and was not carried
over.

## Directory Structure

```text
trivy-operator/
├── application.yaml        # the chart, with every scanner enabled
├── namespace.yaml          # privileged, for node-collector's hostPaths
├── networkpolicy.yaml      # default-deny ingress; Prometheus on 8080
└── grafana-dashboard.yaml  # written for this cluster, not vendored
```
