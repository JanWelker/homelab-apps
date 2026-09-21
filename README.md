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
[homelab.wlkr.ch](https://homelab.wlkr.ch/).

## Applications

| Application | URL | Auth | Manifests | Page |
| --- | --- | --- | --- | --- |
| Home Assistant | `home.k8s.wlkr.ch` | Authentik proxy | [`home-assistant/`](home-assistant/) | [docs](https://janwelker.github.io/homelab-apps/home-assistant/) |
| Nextcloud | `cloud.k8s.wlkr.ch` | Authentik OIDC | [`nextcloud/`](nextcloud/) | [docs](https://janwelker.github.io/homelab-apps/nextcloud/) |
| Trivy Operator | none, it has no UI | none | [`trivy-operator/`](trivy-operator/) | [docs](https://janwelker.github.io/homelab-apps/trivy-operator/) |

## How it works

The `apps` ApplicationSet in the homelab repository generates an ArgoCD
Application from every `*/application.yaml` here, so pushing a directory
deploys an application. These Applications keep `selfHeal`: a hand-edited
resource is reverted within minutes. The flow is on the
[documentation home page](https://janwelker.github.io/homelab-apps/).

## Adding an application

Read [the conventions](docs/conventions.md) first. The step-by-step version is
[Adding a Workload](https://homelab.wlkr.ch/development/add-workload/) in the
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
