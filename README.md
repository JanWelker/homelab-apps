# Homelab Applications

The workloads running on the [homelab
cluster](https://github.com/JanWelker/homelab) — one directory per application,
deployed by ArgoCD.

Documentation for these applications is published at
**[homelab-apps.wlkr.ch](https://homelab-apps.wlkr.ch/)**,
and built from `docs/` in this repository.

This repository holds only the applications. The cluster they run on — Flatcar,
Kubeadm, Cilium, Rook-Ceph, ArgoCD and everything under them — is in
[JanWelker/homelab](https://github.com/JanWelker/homelab), documented at
[homelab.wlkr.ch](https://homelab.wlkr.ch/).

## Applications

| Application | URL | Auth | Manifests | Page |
| --- | --- | --- | --- | --- |
| Home Assistant | `home.k8s.wlkr.ch` | Authentik proxy | [`home-assistant/`](home-assistant/) | [docs](https://homelab-apps.wlkr.ch/home-assistant/) |
| Nextcloud | `cloud.k8s.wlkr.ch` | Authentik OIDC | [`nextcloud/`](nextcloud/) | [docs](https://homelab-apps.wlkr.ch/nextcloud/) |

## How it works

The `apps` ApplicationSet in the homelab repository generates an ArgoCD
Application from every `*/application.yaml` here, so pushing a directory
deploys an application. Every Application syncs automatically, retries a
failed sync and reverts a hand-edited resource within minutes. The flow is on the
[documentation home page](https://homelab-apps.wlkr.ch/).

## Adding an application

Read [the conventions](docs/conventions.md) first. The step-by-step version is
[Adding a Workload](https://homelab.wlkr.ch/development/add-workload/) in the
platform documentation.

A new application needs a page in `docs/`, registered in `zensical.toml`. The
site builds with `--strict`, so an unregistered page fails CI.

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
