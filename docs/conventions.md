---
description: "The rules every application directory in this repository follows, and the reasoning behind each one."
---

# Conventions

Rules every directory in this repository follows. They are short because the
platform does most of the work; [Adding a
Workload](https://homelab.wlkr.ch/development/add-workload/) in the platform
documentation is the long version.

## Structure

One directory per application, named after it, containing exactly one
`application.yaml` — a complete ArgoCD `Application`, not a fragment. The `apps`
ApplicationSet in the [homelab](https://github.com/JanWelker/homelab)
repository generates one Application per `*/application.yaml` it finds here, so
adding a directory adds an application.

Everything beside `application.yaml` is what that Application deploys, which is
why every Application excludes it from its own source:

```yaml
    directory:
      exclude: "application.yaml"
```

## The rules

### 1. `project: apps`

The ApplicationSet fails the whole set rather than generate a workload in the
`infra` or `system` project, which are authorised against destinations a
workload has no business reaching.

### 2. Official upstream sources only

The vendor's own Helm chart, or the vendor's own container image, never a
repackager's. Nextcloud publishes its own chart; Home Assistant publishes
none, so it is plain manifests around the official
`ghcr.io/home-assistant/home-assistant` image.

Pin every version. No `latest`, no floating tags. Renovate moves them, three
days after a release, and the `image-scan.yaml` workflow fails a pull request
whose new image carries a fixable CRITICAL the old one did not — the
[same gate as the platform](https://homelab.wlkr.ch/development/maintenance/#ci-workflows).

!!! warning "Renovate and image fields"
    A custom regex manager for an image field needs `autoReplaceStringTemplate`, or digest pinning fails with `update failure` and takes the shared `renovate/pin-dependencies` branch down with it. A field holding a bare tag has no room for a digest and needs `pinDigests: false` instead. See [Manager rules](https://homelab.wlkr.ch/development/maintenance/#manager-rules) and [renovate#24942](https://github.com/renovatebot/renovate/issues/24942).

### 3. PostgreSQL is always a CloudNativePG `Cluster`

Never the database a chart bundles. Disable it (`internalDatabase.enabled:
false`, `postgresql.enabled: false`) and point the chart at a `Cluster` in the
same namespace through its external-database settings.

The operator writes a `<cluster-name>-app` Secret with `username`, `password`,
`host`, `port`, `dbname` and a ready-assembled `uri`. Consume those keys; never
copy the value into Git or OpenBao.

Give the `Cluster` an earlier sync wave than the application. ArgoCD has a
health check for `postgresql.cnpg.io/Cluster`, so the wave waits for a working
database, not merely a created one:

```yaml
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

Annotate it `Prune=false`, as the PVC and the namespace are: deleting a
`Cluster` deletes the volumes it owns. A chart-rendered PVC needs the same
annotation through the chart's values; `helm.sh/resource-policy: keep` only
survives deleting the Application, not a prune.

The reasoning is in [CloudNativePG &rarr; The
contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract).

### 4. Own your namespace

Ship a `namespace.yaml` at sync wave `-2` carrying the three Pod Security
Admission labels; `CreateNamespace=true` alone leaves an unlabelled namespace
that runs at `privileged`. Set `enforce` to what the application needs and
`audit`/`warn` stricter, so the violations a tighter level would catch stay
visible.

Annotate it `Prune=false`: pruning a `Namespace` deletes every PVC inside it.

### 5. Ship a `CiliumNetworkPolicy`

Not a plain `NetworkPolicy`, which blocks the kubelet's health probes. Every
policy needs `fromEntities: [host, remote-node]` for those probes and
`ingress` for Gateway traffic, and an egress half: the namespace, DNS through
the proxy, and every outside name as `toFQDNs`. The template and the reasons
are in the platform's
[Adding a Workload](https://homelab.wlkr.ch/development/add-workload/#the-network-policy).

Put it at sync wave `-2`, with the namespace:

```yaml
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
```

At the default wave it lands after the `Cluster` from rule 3, and a rule the
`Cluster` needs in order to go Healthy can never unblock the wave it is stuck
behind — see [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database).

### 6. Authentication is Authentik's, not the application's

Which shape applies is decided by what the application supports:

- **It speaks OIDC.** Configure it against Authentik, hide the local login
  form, and keep at most one local admin as break-glass. Nextcloud is the
  worked example.
- **It does not.** Point its `HTTPRoute` at `authentik-server` in the
  `authentik` namespace, so the outpost authenticates in front of it. Home
  Assistant is the worked example; where the application has its own login this
  is defence in depth, not single sign-on.

The OIDC provider's blueprint lives here, in the application's directory, as a
ConfigMap targeted at the `authentik` namespace with a key ending in `.yaml`
(see `nextcloud/authentik-blueprint.yaml`). The client credentials, the
outpost's provider list and any `referencegrant.yaml` entry stay in the
platform repository, so going behind SSO is deliberately two pull requests.

Because blueprint discovery is asynchronous, anything that configures itself
against the provider must tolerate it not existing yet: fail soft and log.
Watch for SSRF guards, too: `auth.k8s.wlkr.ch` resolves to a private address,
and Nextcloud needed `allow_local_remote_servers` before discovery worked.

**Use `auth.k8s.wlkr.ch`**, never `auth.infra.k8s.wlkr.ch`. The `*.infra` zone
resolves only on the local network, and a client must never mix the two, or
the `iss` claim fails against the discovered issuer.

### 7. Real secrets come from OpenBao

An `ExternalSecret` reading `kv/<app>/config`, with the `bao kv put` command
that seeds it in a comment at the top of the file. Database passwords are the
exception, because CloudNativePG generates them (rule 3).

OIDC client credentials go in the application's own `kv/<app>/config`, never
under `kv/authentik/config`: a `bao kv put` replaces a path wholesale, so
sharing it would make adding an application an Authentik outage.

### 8. The shared `syncPolicy`

`automated` with `prune` and `selfHeal`, plus `retry` with a limit of 10 and
a 30s backoff up to 5m, copied from any sibling. ArgoCD never re-attempts a
failed sync of the same revision without `retry`, and a workload that lands a
minute before the platform resource it names would otherwise stay failed
until someone ran `argocd app sync`.

## What you do not have to write

The platform handles all of this; adding your own is the usual mistake:

| You want | You write | The platform does |
| --- | --- | --- |
| A hostname | An `HTTPRoute` on `apps-gateway` | external-dns publishes the Route53 record |
| HTTPS | Nothing | The Gateway holds a `*.k8s.wlkr.ch` wildcard |
| Storage | `storageClassName: rook-ceph-block` | Rook-Ceph replicates it three ways |
| Logs | Nothing | Alloy ships stdout to Loki |
| Backups of a PVC | Nothing | Velero snapshots it on the cluster schedule |
| Metrics | A `ServiceMonitor` or `PodMonitor` | Prometheus scrapes it |

## Behind the Gateway

Traffic arrives from Cilium's Envoy inside the pod CIDR (`10.244.0.0/16`), not
from the client, and TLS is terminated at the Gateway. An application that
trusts `REMOTE_ADDR` sees the proxy, and one that builds absolute URLs from the
request scheme produces `http://` links on an `https://` site. Look for a
trusted-proxies setting and an overwrite-protocol setting; if the login
redirect loops, this is why.
