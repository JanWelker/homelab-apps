---
description: "The applications running on the homelab cluster, how they get deployed, and what they all have in common."
---

# Homelab Applications

The applications the [homelab cluster](https://janwelker.github.io/homelab/)
exists to run. The cluster itself — Flatcar, Kubeadm, Cilium, Rook-Ceph, ArgoCD
and everything under them — is a
[separate repository](https://github.com/JanWelker/homelab) with
[its own documentation](https://janwelker.github.io/homelab/); this site covers
only what runs on top.

## Applications

| Application | URL | Storage | Database | Authentication |
| --- | --- | --- | --- | --- |
| [Home Assistant](home-assistant.md) | [home.k8s.wlkr.ch](https://home.k8s.wlkr.ch) | 5Gi for `/config` | CloudNativePG, for the recorder | Authentik proxy, in front of its own login |
| [Nextcloud](nextcloud.md) | [cloud.k8s.wlkr.ch](https://cloud.k8s.wlkr.ch) | 50Gi for files | CloudNativePG | Authentik OIDC |

## How a directory becomes an application

The `apps` ApplicationSet, which lives in the platform repository, watches this
one and generates an ArgoCD Application from every `*/application.yaml` it
finds. Pushing a directory deploys an application — there is no list to add it
to, and nothing in the other repository to change.

```text
homelab (platform)                    homelab-apps (this repository)
  Application argocd
    └── ApplicationSet platform
          └── Application workloads     ──▶  ApplicationSet apps
                (stage 12-workloads)            └── one Application per directory
```

The `apps` ApplicationSet is created in the platform's last rollout stage, so
nothing here deploys until the whole platform beneath it is healthy. The
dependency runs one way: applications use the platform, and the platform
references this repository exactly once — a `repoURL` — and never reads what is
in it.

One consequence is worth knowing: because these Applications are not under the
platform's `RollingSync` strategy, they keep `selfHeal`. A hand-edited
Deployment here is reverted within minutes, where the same edit to a platform
resource survives until the next commit.
[GitOps Strategy](https://janwelker.github.io/homelab/architecture/gitops/#workloads-live-in-a-second-repository)
covers why the split exists and what it costs.

## What they have in common

Both applications were deployed under the same constraints, and the shape they
share is the one every later one is expected to take. [Conventions](conventions.md)
is the full list; the short version:

- **A CloudNativePG `Cluster` in their own namespace**, never the database
  their chart would have bundled.
- **A namespace they own**, carrying explicit Pod Security Admission labels.
  `CreateNamespace=true` on its own produces an unlabelled namespace, and an
  unlabelled namespace runs at `privileged`.
- **A `CiliumNetworkPolicy`** denying ingress by default, admitting the
  Gateway, the node's health probes and Prometheus.
- **Proxy configuration.** Both sit behind the `apps-gateway`, which terminates
  TLS and forwards from inside the pod CIDR. An application that does not know
  this builds `http://` links on an `https://` site.
- **Authentik, not their own accounts** — as far as each is capable of it.

## Authentication

Both go through
[Authentik](https://janwelker.github.io/homelab/platform/authentik/), but not
in the same way, and the difference is not a preference — it is what each
application supports.

**Nextcloud speaks OIDC.** The first-party `user_oidc` app is installed and
configured by a startup hook, the login form is hidden, and the local admin
survives only as break-glass at `/login?direct=1`. This is real single sign-on:
one login, and revoking the Authentik account ends the access.

**Home Assistant does not.** Upstream ships four auth providers —
`homeassistant`, `command_line`, `trusted_networks` and an example marked
insecure — and no OIDC among them. So the Authentik outpost sits *in front of*
Home Assistant's login rather than replacing it, and browser users authenticate
twice. That is defence in depth, not SSO.

!!! warning "Home Assistant's API is not behind Authentik"
    The companion apps and webhooks hold a long-lived token and cannot complete an interactive login, so `/api/` and `/auth/token` are excluded from the proxy. Home Assistant's own accounts are the only thing guarding them — revoking someone in Authentik does **not** revoke their Home Assistant token, which has to be done in Home Assistant.

Both use `auth.k8s.wlkr.ch`, not the `auth.infra` name the platform UIs use:
the `*.infra` zone resolves only on the local network, so an OIDC client
reachable from outside it would send its users somewhere that does not exist
for them. A client must never mix the two — see [Two
hostnames](https://janwelker.github.io/homelab/platform/authentik/#two-hostnames).

## Adding one

[Conventions](conventions.md) first — it is short, and it is the difference
between an application that works and one that loops on its login redirect. The
step-by-step version is
[Adding a Workload](https://janwelker.github.io/homelab/development/add-workload/)
in the platform documentation.
