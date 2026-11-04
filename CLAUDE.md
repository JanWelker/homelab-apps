# Homelab applications

The workloads that run on the Flatcar homelab cluster. The cluster itself is
the separate `homelab` repository; this one holds only what runs on top.

## Deployment model

A directory with one `application.yaml` is an application; the `apps`
ApplicationSet in `homelab` generates the ArgoCD Application and nothing else
registers it. Everything an application must do is in `docs/conventions.md`,
numbered; read it before adding or changing one. Rules 1, 4 and 5 break the
whole set or the login when missed, and rule 6 means going behind SSO is two
PRs across two repositories. How the platform syncs and retries is in the
platform docs ([GitOps Strategy](https://homelab.wlkr.ch/architecture/gitops/)).

- Long explanations belong in `docs/`, not in YAML comments.
- Changes land through PRs off `main`.

## Reading the docs

`docs/` is the reference for this repository. The platform docs are one fetch
away at <https://homelab.wlkr.ch/llms.txt> (page index) or
<https://homelab.wlkr.ch/llms-full.txt> (every page). This site publishes the
same two at <https://homelab-apps.wlkr.ch/llms.txt> and
<https://homelab-apps.wlkr.ch/llms-full.txt>.

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
