---
description: "The rules every application directory in this repository follows, and the reasoning behind each one."
---

# Conventions

Rules every directory in this repository follows. They are short because the
platform does most of the work; the [Adding a
Workload](https://janwelker.github.io/homelab/development/add-workload/) guide
in the platform documentation is the long version.

## Structure

One directory per application, named after it, containing exactly one
`application.yaml` — a complete ArgoCD `Application`, not a fragment. The `apps`
ApplicationSet in the [homelab](https://github.com/JanWelker/homelab)
repository generates one Application per `*/application.yaml` it finds here.

Adding a directory adds an application. There is no list to register it in, and
nothing in the homelab repository needs to change.

Everything beside `application.yaml` is what that Application deploys, which is
why every Application excludes it from its own source:

```yaml
    directory:
      exclude: "application.yaml"
```

## The rules

### 1. `project: apps`

The ApplicationSet fails the whole set rather than generate a workload in the
`infra` or `system` project. Those are authorised against destinations a
workload has no business reaching.

### 2. Official upstream sources only

The vendor's own Helm chart, or the vendor's own container image. Not a
repackager's chart, however much more convenient it is.

The two applications here are the two shapes this takes:

- **Nextcloud** publishes its own chart, at `https://nextcloud.github.io/helm/`
  from the Nextcloud organisation. Use it.
- **Home Assistant** publishes no chart at all. The popular community charts
  are third-party repackagers, so this is plain manifests around the official
  `ghcr.io/home-assistant/home-assistant` image instead. Writing a Deployment
  is less work than auditing somebody else's chart on every bump.

Pin every version. No `latest`, no floating tags. Renovate moves them.

### 3. PostgreSQL is always a CloudNativePG `Cluster`

Never the database a chart bundles — disable it (`internalDatabase.enabled:
false`, `postgresql.enabled: false`) and point the chart at a `Cluster` in the
same namespace through its external-database settings.

The operator writes a `<cluster-name>-app` Secret with `username`, `password`,
`host`, `port`, `dbname` and a ready-assembled `uri`. Consume those keys; never
copy the value into Git, and never put it in OpenBao either — nothing outside
the cluster needs it.

Give the `Cluster` an earlier sync wave than the application in front of it.
ArgoCD has a built-in health check for `postgresql.cnpg.io/Cluster`, so the
wave genuinely waits for a working database rather than merely a created one:

```yaml
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

The reasoning is in [CloudNativePG &rarr; The
contract](https://janwelker.github.io/homelab/platform/cloudnative-pg/#the-contract).

### 4. Own your namespace

Ship a `namespace.yaml` at sync wave `-2` carrying the three Pod Security
Admission labels. A namespace nobody labelled runs at `privileged`, which
enforces nothing — `CreateNamespace=true` alone leaves exactly that.

Set `enforce` to what the application demonstrably needs and `audit`/`warn`
stricter, so the violations a tighter level would catch stay visible.

Annotate it `Prune=false`. Pruning a `Namespace` deletes every PVC inside it,
and a misplaced deletion in Git should not become permanent data loss three
minutes later.

### 5. Ship a `CiliumNetworkPolicy`

Not a plain `NetworkPolicy` — a plain one blocks the kubelet's health probes
and the pods restart forever. Every policy here needs `fromEntities: [host,
remote-node]` for those probes and `ingress` for Gateway traffic.

### 6. Authentication is Authentik's, not the application's

An application with its own user database is an application whose accounts
nobody remembers to revoke. Which shape applies is decided by what the
application supports, not by preference:

- **It speaks OIDC** — configure it against Authentik, hide or disable the
  local login form, and keep at most one local admin as break-glass. Nextcloud
  is the worked example.
- **It does not** — point its `HTTPRoute` at `authentik-server` in the
  `authentik` namespace instead of at the application, so the outpost
  authenticates in front of it. Home Assistant is the worked example, and also
  the honest caveat: where the application has a login of its own, this is
  defence in depth rather than single sign-on.

An OIDC provider's blueprint belongs **here**, in the application's own
directory, as a ConfigMap targeted at the `authentik` namespace — see
`nextcloud/authentik-blueprint.yaml`. The key must end in `.yaml` or Authentik
never discovers it, and the platform needs one projected-volume source added
for the mount.

What stays in the platform repository either way: the client credentials
(`bao-secrets.sh`), the embedded outpost's provider list, and for a proxied
application its `referencegrant.yaml` entry. A workload cannot mint its own
client credentials, so going behind SSO is still deliberately two pull
requests — a workload should not be able to take itself out from behind the
authentication layer on its own.

Because discovery is asynchronous, anything that configures itself *against* a
provider has to tolerate the provider not existing yet. Fail soft and log it;
do not make it the reason the pod will not start.

**Use `auth.k8s.wlkr.ch`**, never `auth.infra.k8s.wlkr.ch`. The `*.infra` zone
resolves only on the local network, so a client reachable from outside it would
send its users to an authorize endpoint that does not exist for them. Never mix
the two in one client: the `iss` claim must match the issuer that was
discovered.

### 7. Real secrets come from OpenBao

An `ExternalSecret` reading `kv/<app>/config`, with the `bao kv put` command
that seeds it written in a comment at the top of the file. Nothing sensitive is
committed, and the next person rebuilding the cluster can see what needs to
exist.

Database passwords are the exception, and only because CloudNativePG generates
them — see rule 3. OIDC client credentials go in the application's own
`kv/<app>/config`, never as extra keys under `kv/authentik/config`: that path
is replaced wholesale on every write, so sharing it would make adding an
application an Authentik outage.

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

Both applications here needed proxy configuration, and it is the single most
common thing to get wrong. Traffic arrives from Cilium's Envoy inside the pod
CIDR (`10.244.0.0/16`), not from the client, and TLS is terminated at the
Gateway — so an application that trusts `REMOTE_ADDR` sees the proxy, and one
that builds absolute URLs from the request scheme builds `http://` links on an
`https://` site.

Look for a trusted-proxies setting and an "overwrite protocol" setting in
whatever you are deploying. If the login redirect loops, this is why.
