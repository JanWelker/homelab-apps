---
description: "Home Assistant on the cluster: plain manifests around the official image, two kinds of state in two places, and an Authentik proxy in front of its own login."
---

# Home Assistant

[Home Assistant](https://www.home-assistant.io/) runs the house. Upstream
publishes no Helm chart and the community ones are repackagers, so this is a
Deployment, a Service, a PVC and a ConfigMap around the official image, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [home.k8s.wlkr.ch](https://home.k8s.wlkr.ch) |
| Authentication | Authentik proxy outpost, in front of Home Assistant's own login |
| Storage | 5Gi `rook-ceph-block` PVC for `/config` |
| Database | CloudNativePG `Cluster` `home-assistant-db`, for the recorder |
| Files | [`home-assistant/`](https://github.com/JanWelker/homelab-apps/tree/main/home-assistant) |

## State

| State | Where | Rebuildable? |
| --- | --- | --- |
| Registries, users, tokens, integration config (`/config/.storage`) | The `home-assistant-config` PVC | **No.** Losing it means re-pairing every device |
| History and long-term statistics | PostgreSQL, via CloudNativePG | Only from a backup |
| `configuration.yaml` | A ConfigMap, in Git | Yes |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests, no chart | Home Assistant is one stateful process with one volume and one port; a Deployment is less work than auditing a third-party chart on every bump |
| Recorder on CloudNativePG, not SQLite | SQLite's locking on a network block device is the usual cause of a Home Assistant that feels slow. `purge_keep_days` is raised because the default of 10 is shorter than the moment you look for a graph. See [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract) |
| `secrets.yaml` written by an init container on every start | Home Assistant has no `!env_var` tag, so the database URL reaches `configuration.yaml` through `!secret`, from CloudNativePG's Secret. Anything added to that file by hand is lost at the next restart; secrets belong in [OpenBao](https://homelab.wlkr.ch/platform/openbao/) |
| `use_x_forwarded_for` with the pod CIDR in `trusted_proxies` | Requests arrive from Cilium's Envoy and the outpost. Without it every request has one source address, so the ban list and rate limiting count the household as one user |
| `HTTPRoute` targets `authentik-server`, not the app | The outpost authenticates and forwards to `home-assistant.home-assistant.svc:8123`. Home Assistant is the one proxied app with a login of its own, so browser users log in twice: defence in depth, not SSO |
| `CiliumNetworkPolicy` admits 8123 from the `authentik` namespace only | No `fromEntities: ingress`, so a request straight from the Gateway cannot skip the outpost |
| Policy admits `cnpg-system` to the database pod on 8000, at sync wave `-2` | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |

## Usage

The ConfigMap is mounted over `/config/configuration.yaml` and read once at
startup, so a merged change does nothing until the pod restarts:

```bash
kubectl -n home-assistant rollout restart deploy/home-assistant
```

The UI's own restart button does the same from inside.

## Health check

```bash
kubectl -n home-assistant get pods,pvc
kubectl -n home-assistant get cluster home-assistant-db
```

The database should report `Cluster in healthy state`. A pod stuck in `Init`
is waiting on it: the init container cannot write `secrets.yaml` until
CloudNativePG has produced the Secret.

## Pitfalls

!!! warning "The API is not behind Authentik"
    The companion apps and every webhook authenticate with a long-lived token and cannot complete an interactive login, so `skip_path_regex` on the provider lets `/api/`, `/auth/token` and the external-auth callback through. Home Assistant's own accounts are the only thing guarding those paths. Revoking an Authentik account does not revoke a Home Assistant token; do that under Settings → People.

- **No local device discovery.** mDNS and SSDP need host networking, which
  needs a `privileged` namespace. Add devices by IP, or through an integration
  that does not rely on broadcast.
- **No USB devices.** A Zigbee or Z-Wave stick pins the pod to one machine.
  Use a network-attached coordinator instead.
- **The cluster is now a dependency of the lights.** A Ceph rebalance that
  pauses I/O pauses Home Assistant with it.
