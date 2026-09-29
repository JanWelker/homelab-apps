---
description: "The applications running on the homelab cluster, how they get deployed, and what they all have in common."
---

# Homelab Applications

The applications the [homelab cluster](https://homelab.wlkr.ch/) exists to
run. The cluster itself — Flatcar, Kubeadm, Cilium, Rook-Ceph, ArgoCD and
everything under them — is a
[separate repository](https://github.com/JanWelker/homelab) with
[its own documentation](https://homelab.wlkr.ch/); this site covers only what
runs on top.

## Applications

| Application | URL | Storage | Database | Authentication |
| --- | --- | --- | --- | --- |
| [Dependency-Track](dependency-track.md) | [sbom.k8s.wlkr.ch](https://sbom.k8s.wlkr.ch) | A PVC for uploaded BOMs and mirrored feeds | CloudNativePG | Authentik OIDC |
| [Flowscape](flowscape.md) | [flowscape.k8s.wlkr.ch](https://flowscape.k8s.wlkr.ch) | None | None | Authentik proxy |
| [Home Assistant](home-assistant.md) | [home.k8s.wlkr.ch](https://home.k8s.wlkr.ch) | A PVC for `/config` | CloudNativePG, for the recorder | Authentik proxy, in front of its own login |
| [Jellyfin](jellyfin.md) | [media.k8s.wlkr.ch](https://media.k8s.wlkr.ch) | Three PVCs: the library, the configuration, the transcode cache | None; SQLite on the configuration volume | Authentik proxy, in front of its own login |
| [Nextcloud](nextcloud.md) | [cloud.k8s.wlkr.ch](https://cloud.k8s.wlkr.ch) | A PVC for files | CloudNativePG | Authentik OIDC |
| [Open WebUI](open-webui.md) | [chat.k8s.wlkr.ch](https://chat.k8s.wlkr.ch) | A PVC for uploads and the retrieval index | CloudNativePG | Authentik OIDC |
| [Paperless-ngx](paperless-ngx.md) | [paperless.k8s.wlkr.ch](https://paperless.k8s.wlkr.ch) | Two PVCs: the archive, and the index and consume folder | CloudNativePG | Authentik OIDC |
| [OpenClaw](openclaw.md) | [claw.k8s.wlkr.ch](https://claw.k8s.wlkr.ch) | One PVC: state, workspace and channel credentials | None | Authentik proxy, in front of its own token |
| [Umami](umami.md) | [analytics.k8s.wlkr.ch](https://analytics.k8s.wlkr.ch) | None | CloudNativePG | Authentik proxy, in front of its own login; the tracker paths are public |
| [Wollbi Adventsfenster](advent-wollbi.md) | [advent.wollbi.ch](https://advent.wollbi.ch) | A PVC for uploads | CloudNativePG | Public; Authentik proxy on `/admin` only |
| [Wollbi-Fescht](fest-wollbi.md) | [fest.wollbi.ch](https://fest.wollbi.ch) | A PVC for uploads | CloudNativePG | Public; Authentik proxy on `/admin` only |

## How a directory becomes an application

The `apps` ApplicationSet in the platform repository watches this one and
generates an ArgoCD Application from every `*/application.yaml` it finds.
Pushing a directory deploys an application; there is no list to register it in.

```text
homelab (platform)                    homelab-apps (this repository)
  Application argocd
    └── ApplicationSet platform
          └── Application workloads     ──▶  ApplicationSet apps
                                                └── one Application per directory
```

The platform references this repository exactly once, as a `repoURL`, and
never reads what is in it. Nothing orders a workload after the platform it
uses: each Application syncs as soon as it exists and retries until the
Gateway, StorageClass or `ClusterSecretStore` it names is there — the
[sync policy](conventions.md#8-the-shared-syncpolicy) is the same one every
platform Application carries. Why the split exists is in
[GitOps Strategy](https://homelab.wlkr.ch/architecture/gitops/#workloads-live-in-a-second-repository).

## What they have in common

Every directory follows the same eight rules, each with one sentence of why:
[Conventions](conventions.md).

## Authentication

Every application goes through
[Authentik](https://homelab.wlkr.ch/platform/authentik/), in the shape each one
supports. [Nextcloud](nextcloud.md) and [Dependency-Track](dependency-track.md)
speak OIDC, so they are real single sign-on with one local admin kept as
break-glass. [Home Assistant](home-assistant.md) and
[Umami](umami.md) ship no OIDC provider, so the Authentik outpost sits in
front of their own logins and browser users authenticate twice;
[Flowscape](flowscape.md) has no login, so the outpost is the only one. All
use `auth.k8s.wlkr.ch`, never the `auth.infra` name, which resolves only on
the local network — see
[Two hostnames](https://homelab.wlkr.ch/platform/authentik/#two-hostnames).

## Adding one

Read [Conventions](conventions.md) first; it is short. The step-by-step version
is [Adding a Workload](https://homelab.wlkr.ch/development/add-workload/) in the
platform documentation.
