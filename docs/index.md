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
| [Flowscape](flowscape.md) | [flowscape.k8s.wlkr.ch](https://flowscape.k8s.wlkr.ch) | None | None | Authentik proxy |
| [Home Assistant](home-assistant.md) | [home.k8s.wlkr.ch](https://home.k8s.wlkr.ch) | A PVC for `/config` | CloudNativePG, for the recorder | Authentik proxy, in front of its own login |
| [Nextcloud](nextcloud.md) | [cloud.k8s.wlkr.ch](https://cloud.k8s.wlkr.ch) | A PVC for files | CloudNativePG | Authentik OIDC |

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

Both user-facing applications go through
[Authentik](https://homelab.wlkr.ch/platform/authentik/), in the shape each one
supports. [Nextcloud](nextcloud.md) speaks OIDC, so it is real single sign-on
with the local login hidden. [Home Assistant](home-assistant.md) ships no OIDC
provider, so the Authentik outpost sits in front of its own login and browser
users authenticate twice. Both use `auth.k8s.wlkr.ch`, never the `auth.infra`
name, which resolves only on the local network — see
[Two hostnames](https://homelab.wlkr.ch/platform/authentik/#two-hostnames).

## Adding one

Read [Conventions](conventions.md) first; it is short. The step-by-step version
is [Adding a Workload](https://homelab.wlkr.ch/development/add-workload/) in the
platform documentation.
