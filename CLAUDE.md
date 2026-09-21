# Homelab applications

The workloads that run on the Flatcar homelab cluster. The cluster itself is
the separate `homelab` repository; this one holds only what runs on top.

## Deployment model

The `apps` ApplicationSet in the `homelab` repository generates one ArgoCD
Application per `*/application.yaml` here. A directory is an application; there
is no list to register it in and nothing in the other repository to change.

- Each directory holds exactly one `application.yaml`, a complete Application,
  plus the manifests it deploys. The Application excludes `application.yaml`
  from its own source.
- The platform never reads this repository beyond its `repoURL`. Nothing
  orders a workload after the platform it references: the Application syncs
  as soon as it exists and retries until the Gateway, StorageClass or
  `ClusterSecretStore` it names is there.
- Every `application.yaml` carries the same `syncPolicy`: `automated` with
  `prune` and `selfHeal`, plus `retry` (limit 10, 30s backoff up to 5m).
  ArgoCD never re-attempts a failed sync of the same revision without it. A
  hand-edited resource is reverted within minutes.
- Each version is pinned once, in `application.yaml`. Renovate moves it.

The rules every directory follows are in `docs/conventions.md`. The ones that
break the whole set or the login if missed:

- `project: apps`, or the ApplicationSet refuses every application.
- Official upstream charts and images only, never a repackager's.
- PostgreSQL is a CloudNativePG `Cluster` at sync wave `-1`, never the chart's
  bundled one.
- `namespace.yaml` with Pod Security labels and `Prune=false`, and a
  `CiliumNetworkPolicy`, both at sync wave `-2`. A policy at wave `0` cannot
  unblock a `Cluster` stuck at `-1`.
- Authentik on `auth.k8s.wlkr.ch`, never `auth.infra.k8s.wlkr.ch`. OIDC
  credentials come from `kv/<app>/config` in OpenBao, seeded by the platform's
  `bao-secrets.sh`, so going behind SSO is two PRs across two repositories.
- Long explanations belong in `docs/`, not in YAML comments.
- Changes land through PRs off `main`.

## Checks before pushing

```bash
uv run yamllint .
uv run zensical build --clean --strict        # docs site; validates links and anchors
npx --package markdownlint-cli2 markdownlint-cli2 '**/*.md' '!**/.venv' '!site'
npx --package renovate@latest renovate-config-validator
```

## Writing docs

`docs/` is reference material, not an essay collection. One page per
application, registered in `zensical.toml`, plus `conventions.md`.

- **Application pages share one skeleton:** intro, At a glance, Configuration,
  Usage, Health check, Pitfalls, and Recovery only where a real runbook exists.
- **Say each fact once.** The rules live in `conventions.md`; an application
  page states how it applies them in one clause and links. Platform facts live
  in the platform docs at `https://homelab.wlkr.ch/`; link, do not restate.
- **One sentence of why per rule.** No history, postmortems, measurements of
  the day, or "this page previously claimed".
- **Never restate values from the manifests.** Link the file and explain why the
  setting is what it is.
- **Tables and numbered steps over prose.** Headings are nouns a reader would
  search for, not essay titles.
- The build validates links and anchors. Grep for `#anchor` before renaming a
  heading, in this repository and in `homelab`.
