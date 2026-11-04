# Homelab Applications

The applications the [homelab cluster](<https://homelab.wlkr.ch/>) exists to run. The cluster itself — Flatcar, Kubeadm, Cilium, Rook-Ceph, ArgoCD and everything under them — is a [separate repository](<https://github.com/JanWelker/homelab>) with [its own documentation](<https://homelab.wlkr.ch/>); this site covers only what runs on top.

## Applications

| Application | URL | Storage | Database | Authentication |
| --- | --- | --- | --- | --- |
| [Claude agents](<https://homelab-apps.wlkr.ch/claude-agents/index.md>) | `<session>.ssh.wlkr.ch` | One PVC per session: `$HOME`, clone and login | None | SSH public keys |
| [Dependency-Track](<https://homelab-apps.wlkr.ch/dependency-track/index.md>) | [sbom.k8s.wlkr.ch](<https://sbom.k8s.wlkr.ch>) | A PVC for uploaded BOMs and mirrored feeds | CloudNativePG | Authentik OIDC |
| [Flowscape](<https://homelab-apps.wlkr.ch/flowscape/index.md>) | [flowscape.k8s.wlkr.ch](<https://flowscape.k8s.wlkr.ch>) | None | None | Authentik proxy |
| [Home Assistant](<https://homelab-apps.wlkr.ch/home-assistant/index.md>) | [home.k8s.wlkr.ch](<https://home.k8s.wlkr.ch>) | A PVC for `/config` | CloudNativePG, for the recorder | Authentik proxy, in front of its own login |
| [OpenCloud](<https://homelab-apps.wlkr.ch/opencloud/index.md>) | [cloud.infra.k8s.wlkr.ch](<https://cloud.infra.k8s.wlkr.ch>) | A PVC for the files, metadata and index | None | Authentik OIDC, web and native clients |
| [Umami](<https://homelab-apps.wlkr.ch/umami/index.md>) | [analytics.k8s.wlkr.ch](<https://analytics.k8s.wlkr.ch>) | None | CloudNativePG | Authentik proxy, in front of its own login; the tracker paths are public |
| [Wollbi Adventsfenster](<https://homelab-apps.wlkr.ch/advent-wollbi/index.md>) | [advent.wollbi.ch](<https://advent.wollbi.ch>) | A PVC for uploads | CloudNativePG | Public; Authentik proxy on `/admin` only |
| [Wollbi-Fescht](<https://homelab-apps.wlkr.ch/fest-wollbi/index.md>) | [fest.wollbi.ch](<https://fest.wollbi.ch>) | A PVC for uploads | CloudNativePG | Public; Authentik proxy on `/admin` only |

## How a directory becomes an application

The `apps` ApplicationSet in the platform repository watches this one and generates an ArgoCD Application from every `*/application.yaml` it finds. Pushing a directory deploys an application; there is no list to register it in.

```text
homelab (platform)                    homelab-apps (this repository)
  Application argocd
    └── ApplicationSet platform
          └── Application workloads     ──▶  ApplicationSet apps
                                                └── one Application per directory
```

The platform references this repository exactly once, as a `repoURL`, and never reads what is in it. Nothing orders a workload after the platform it uses: each Application syncs as soon as it exists and retries until the Gateway, StorageClass or `ClusterSecretStore` it names is there — the [sync policy](<https://homelab-apps.wlkr.ch/conventions/#8-the-shared-syncpolicy>) is the same one every platform Application carries. Why the split exists is in [GitOps Strategy](<https://homelab.wlkr.ch/architecture/gitops/#workloads-live-in-a-second-repository>).

## What they have in common

Every directory follows the same eight rules, each with one sentence of why: [Conventions](<https://homelab-apps.wlkr.ch/conventions/index.md>).

## Authentication

Every application goes through [Authentik](<https://homelab.wlkr.ch/platform/authentik/>), in the shape each one supports. [Dependency-Track](<https://homelab-apps.wlkr.ch/dependency-track/index.md>) and [OpenCloud](<https://homelab-apps.wlkr.ch/opencloud/index.md>) speak OIDC, so they are real single sign-on. [Home Assistant](<https://homelab-apps.wlkr.ch/home-assistant/index.md>) and [Umami](<https://homelab-apps.wlkr.ch/umami/index.md>) ship no OIDC provider, so the Authentik outpost sits in front of their own logins and browser users authenticate twice; [Flowscape](<https://homelab-apps.wlkr.ch/flowscape/index.md>) has no login, so the outpost is the only one. All use `auth.k8s.wlkr.ch`, never the `auth.infra` name, which resolves only on the local network — see [Two hostnames](<https://homelab.wlkr.ch/platform/authentik/#two-hostnames>).

## Adding one

Read [Conventions](<https://homelab-apps.wlkr.ch/conventions/index.md>) first; it is short. The step-by-step version is [Adding a Workload](<https://homelab.wlkr.ch/development/add-workload/>) in the platform documentation.
