# Homelab Applications

The workloads running on the [homelab
cluster](https://github.com/JanWelker/homelab) — one directory per application,
deployed by ArgoCD.

This repository holds only the applications. The cluster they run on — Flatcar,
Kubeadm, Cilium, Rook-Ceph, ArgoCD and everything under them — is in
[JanWelker/homelab](https://github.com/JanWelker/homelab), and its
documentation is published at
**[janwelker.github.io/homelab](https://janwelker.github.io/homelab/)**.

## Applications

| Application | URL | Storage | Database |
| --- | --- | --- | --- |
| [home-assistant](home-assistant/) | `home.k8s.wlkr.ch` | 5Gi `/config` | CloudNativePG, for the recorder |
| [nextcloud](nextcloud/) | `cloud.k8s.wlkr.ch` | 50Gi data | CloudNativePG |

## How it works

The `apps` ApplicationSet in the homelab repository watches this one and
generates an ArgoCD Application from every `*/application.yaml` it finds.
Pushing a new directory deploys an application; there is no list to add it to
and nothing in the other repository to change.

```text
homelab (platform)                    homelab-apps (this repository)
  Application argocd
    └── ApplicationSet platform
          └── Application workloads     ──▶  ApplicationSet apps
                (stage 12-workloads)            └── one Application per directory
```

The `apps` ApplicationSet is created in the platform's last rollout stage, so
nothing here is deployed until the whole platform beneath it is healthy. The
dependency runs one way: workloads use the platform, and the platform
references this repository exactly once — a `repoURL` — and never reads what is
in it.

Because these Applications are not under the platform's `RollingSync` strategy,
they keep `selfHeal`: a hand-edited Deployment here is reverted within minutes.

## Adding an application

Read [CONVENTIONS.md](CONVENTIONS.md) first — it is short, and it is the
difference between an application that works and one that loops on its login
redirect. The step-by-step version is [Adding a
Workload](https://janwelker.github.io/homelab/development/add-workload/).

The rules that catch people out:

- `project: apps`, or the ApplicationSet refuses the whole set.
- Official upstream charts and images only, never a repackager's.
- PostgreSQL is always a CloudNativePG `Cluster`, never the chart's bundled one.
- Ship a `namespace.yaml` with Pod Security labels and a `CiliumNetworkPolicy`.

## Local checks

The same linters CI runs:

```bash
yamllint .
markdownlint-cli2 '**/*.md'
npx --package renovate@latest renovate-config-validator
```

Rendering an application the way ArgoCD will, before pushing it:

```bash
helm template nextcloud nextcloud \
  --repo https://nextcloud.github.io/helm/ \
  --version "$(awk '/chart: nextcloud/{f=1} f&&/targetRevision:/{print $2; exit}' nextcloud/application.yaml)"
```
