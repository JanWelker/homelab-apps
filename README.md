# Homelab Applications

The workloads running on the [homelab
cluster](https://github.com/JanWelker/homelab) — one directory per application,
deployed by ArgoCD.

Documentation for these applications is published at
**[janwelker.github.io/homelab-apps](https://janwelker.github.io/homelab-apps/)**,
and built from `docs/` in this repository.

This repository holds only the applications. The cluster they run on — Flatcar,
Kubeadm, Cilium, Rook-Ceph, ArgoCD and everything under them — is in
[JanWelker/homelab](https://github.com/JanWelker/homelab), documented at
[janwelker.github.io/homelab](https://janwelker.github.io/homelab/).

## Applications

| Application | URL | Auth | Manifests | Page |
| --- | --- | --- | --- | --- |
| Home Assistant | `home.k8s.wlkr.ch` | Authentik proxy | [`home-assistant/`](home-assistant/) | [docs](https://janwelker.github.io/homelab-apps/home-assistant/) |
| Nextcloud | `cloud.k8s.wlkr.ch` | Authentik OIDC | [`nextcloud/`](nextcloud/) | [docs](https://janwelker.github.io/homelab-apps/nextcloud/) |
| Trivy Operator | none, it has no UI | none | [`trivy-operator/`](trivy-operator/) | [docs](https://janwelker.github.io/homelab-apps/trivy-operator/) |

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

Read [the conventions](docs/conventions.md) first — they are short, and they
are the difference between an application that works and one that loops on its
login redirect. The step-by-step version is [Adding a
Workload](https://janwelker.github.io/homelab/development/add-workload/) in the
platform documentation.

A new application needs a page in `docs/`, registered in `zensical.toml`. The
site builds with `--strict`, so an unregistered page fails CI.

The rules that catch people out:

- `project: apps`, or the ApplicationSet refuses the whole set.
- Official upstream charts and images only, never a repackager's.
- PostgreSQL is always a CloudNativePG `Cluster`, never the chart's bundled one.
- Ship a `namespace.yaml` with Pod Security labels and a `CiliumNetworkPolicy`.
- Authentication is Authentik's, on `auth.k8s.wlkr.ch` — never the `auth.infra`
  name, which resolves only on the local network.

## Local checks

The same linters CI runs:

```bash
uv sync                      # once
uv run yamllint .
uv run zensical build --clean --strict
npx --package markdownlint-cli2 markdownlint-cli2 '**/*.md' '!**/.venv' '!site'
npx --package renovate@latest renovate-config-validator
```

Previewing the docs site while writing:

```bash
uv run zensical serve
```

Rendering an application the way ArgoCD will, before pushing it:

```bash
helm template nextcloud nextcloud \
  --repo https://nextcloud.github.io/helm/ \
  --version "$(awk '/chart: nextcloud/{f=1} f&&/targetRevision:/{print $2; exit}' nextcloud/application.yaml)"
```
