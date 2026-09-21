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
| [Home Assistant](home-assistant.md) | [home.k8s.wlkr.ch](https://home.k8s.wlkr.ch) | 5Gi for `/config` | CloudNativePG, for the recorder | Authentik proxy, in front of its own login |
| [Nextcloud](nextcloud.md) | [cloud.k8s.wlkr.ch](https://cloud.k8s.wlkr.ch) | 50Gi for files | CloudNativePG | Authentik OIDC |
| [Trivy Operator](trivy-operator.md) | — | 5Gi for the vulnerability database | None — findings are CRDs | None; it has no interface |

Trivy Operator has no UI and nothing to log into. It lives here rather than in
the platform repository because it is a workload *on* the cluster: nothing the
platform brings up depends on it.

## How a directory becomes an application

The `apps` ApplicationSet in the platform repository watches this one and
generates an ArgoCD Application from every `*/application.yaml` it finds.
Pushing a directory deploys an application; there is no list to register it in.

```text
homelab (platform)                    homelab-apps (this repository)
  Application argocd
    └── ApplicationSet platform
          └── Application workloads     ──▶  ApplicationSet apps
                (stage 12-workloads)            └── one Application per directory
```

The `apps` ApplicationSet is created in the platform's last rollout stage, so
nothing here deploys until the whole platform beneath it is healthy. The
platform references this repository exactly once, as a `repoURL`, and never
reads what is in it.

These Applications are not under the platform's `RollingSync` strategy, so they
keep `selfHeal`: a hand-edited Deployment is reverted within minutes. Why the
split exists is in
[GitOps Strategy](https://homelab.wlkr.ch/architecture/gitops/#workloads-live-in-a-second-repository).

## What they have in common

[Conventions](conventions.md) is the full list. The short version:

- **A namespace they own**, with explicit Pod Security Admission labels.
- **A `CiliumNetworkPolicy`** denying ingress by default.
- **A CloudNativePG `Cluster`**, never a chart's bundled database.
- **Proxy configuration** for the `apps-gateway`, which terminates TLS and
  forwards from inside the pod CIDR.
- **Authentik, not their own accounts**, as far as each is capable of it.

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
