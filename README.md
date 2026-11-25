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
[homelab.wlkr.ch](https://homelab.wlkr.ch/). LLM clients can read this site as
[llms.txt](https://homelab-apps.wlkr.ch/llms.txt) or in full as
[llms-full.txt](https://homelab-apps.wlkr.ch/llms-full.txt); the platform site
publishes the same two files.

The applications, what each stores and how it signs in, and how a directory
becomes an ArgoCD Application are on the
[documentation home page](https://homelab-apps.wlkr.ch/).

## Forking

The platform names this repository twice, in the `apps` ApplicationSet's
`repoURL` and the `apps` project's `sourceRepos`, and lists workload
namespaces by name (rules 6 and 7 of [the conventions](docs/conventions.md)).
Here, the author's values sit in:

- every `*/application.yaml` `repoURL` that points at this repository
- `docs/CNAME`
- `zensical.toml`: `site_url`, `repo_url`, `copyright`
- `.github/CODEOWNERS`
- the reusable workflow `.github/workflows/ci-ok.yaml` calls
- the shared Renovate preset `renovate.json` extends
- the analytics partial in `overrides/partials/integrations/analytics/`

## Adding an application

Read [the conventions](docs/conventions.md) first. The step-by-step version is
[Adding a Workload](https://homelab.wlkr.ch/development/add-workload/) in the
platform documentation.

A new application needs a page in `docs/`, registered in `zensical.toml` under
`nav` and under `plugins.llmstxt.sections` (which builds `llms.txt` for LLM
clients). The site builds with `--strict`, so an unregistered page fails CI.

## Local checks

The same linters CI runs:

```bash
uv sync                      # once
uv run pre-commit install    # once; runs the linters below on every commit
uv run yamllint --strict -f github .
uv run zensical build --clean --strict
npx --package markdownlint-cli2 markdownlint-cli2 '**/*.md' '!**/.venv' '!site'
npx --package renovate@latest renovate-config-validator
uv run ruff check . && uv run ruff format --check .   # scripts/ and tests/
uv run pytest -q
```

The `Secret Scan` workflow runs gitleaks over every pull request's commits, at the
version of the pre-commit hook; a manual run scans the whole history.

Previewing the docs site while writing:

```bash
uv run zensical serve
```

Rendering every chart-based application with its values, the way ArgoCD and
the `Render Charts` workflow do, into `.cache/rendered/`:

```bash
make render
```
