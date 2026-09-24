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
| Storage | `rook-ceph-block` PVC for `/config` |
| Database | CloudNativePG `Cluster` `home-assistant-db`, for the recorder |
| Files | [`home-assistant/`](https://github.com/JanWelker/homelab-apps/tree/main/home-assistant) |

## State

| State | Where | Rebuildable? |
| --- | --- | --- |
| Registries, users, tokens, integration config (`/config/.storage`) | The `home-assistant-config` PVC | **No.** Losing it means re-pairing every device; the nightly [Velero snapshot](https://homelab.wlkr.ch/operations/backups/) is the only copy |
| History and long-term statistics | PostgreSQL, via CloudNativePG | Only from the same Velero snapshot, which is crash-consistent, not point in time |
| `configuration.yaml` | A ConfigMap, in Git | Yes |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests, no chart | Home Assistant is one stateful process with one volume and one port; a Deployment is less work than auditing a third-party chart on every bump |
| `strategy: Recreate`, one replica | The `/config` PVC is `ReadWriteOnce`, and two Home Assistant processes against one `/config` corrupt the `.storage` registries |
| `revisionHistoryLimit: 2` | Superseded ReplicaSets keep their Trivy config-audit reports until they are garbage-collected; the Kubernetes default keeps ten |
| Seccomp only; the namespace enforces `baseline` | The image runs as root under s6 and writes `/config`, and upstream does not support running it otherwise, so `runAsNonRoot` and a read-only root do not apply |
| An init container from the same image seeds `/config` on every start | `configuration.yaml` includes `automations.yaml`, `scripts.yaml` and `scenes.yaml` so the UI editors can save; on a fresh volume they do not exist and Home Assistant fails to start rather than create them. Same image as the main container because Renovate updates every occurrence in one pull request, so the two cannot drift |
| A long `startupProbe` | Home Assistant loads every integration before it serves anything, minutes rather than seconds on a cold start with a populated registry. The startup probe buys that time without making the liveness probe useless afterwards |
| Recorder on CloudNativePG, not SQLite | SQLite's locking on a network block device is the usual cause of a Home Assistant that feels slow. `purge_keep_days` is raised because the default of 10 is shorter than the moment you look for a graph. See [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract) |
| `secrets.yaml` written by the init container on every start | Home Assistant has no `!env_var` tag, so the database URL reaches `configuration.yaml` through `!secret`, from CloudNativePG's Secret, which the operator rotates. The value is written through `json.dumps` so it is valid YAML whatever the generated password contains. Anything added to that file by hand is lost at the next restart; secrets belong in [OpenBao](https://homelab.wlkr.ch/platform/openbao/) |
| `use_x_forwarded_for` with the pod CIDR in `trusted_proxies` | Requests arrive from Cilium's Envoy and the outpost. Without it every request has one source address, so the ban list and rate limiting count the household as one user |
| `HTTPRoute` targets `authentik-server`, not the app | The outpost authenticates and forwards to `home-assistant.home-assistant.svc:8123`. Home Assistant is the one proxied app with a login of its own, so browser users log in twice: defence in depth, not SSO. The cross-namespace `backendRef` works only because the platform's `referencegrant.yaml` names this namespace. Pointing the route at the Home Assistant Service instead silently removes the whole authentication layer, so it deserves a second look in review |

### Network policy

Every rule in `home-assistant/networkpolicy.yaml`, and why it is there. The
shape is [Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

| Rule | Why |
| --- | --- |
| Ingress on 8123 from the Authentik server pods only | The outpost is the only path to the UI. No `fromEntities: ingress`, so a request straight from the Gateway cannot skip it. Nothing else in the cluster has a reason to connect: this namespace holds a long-lived token for every device in the house. With the rule missing, the hostname answers with a gateway error after a successful Authentik login |
| Ingress from Prometheus on 9187 | The database's metrics |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |
| Egress to `*.home-assistant.io` | The alerts feed and version data. An integration that talks to a device or a cloud is a line here first |
| Egress to the multicast and limited-broadcast ranges on 5353 and 1900 | The mDNS and SSDP discovery sockets keep sending, and the overlay carries it nowhere. Allowed only so it does not fill the drop log |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

## Usage

The ConfigMap is mounted over `/config/configuration.yaml`, so Git is the
source of truth and the UI cannot edit it; everything Home Assistant writes for
itself stays on the PVC underneath. The file is read once at startup, so a
merged change does nothing until the pod restarts:

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
  that does not rely on broadcast, and add the address to the egress policy.
- **No USB devices.** A Zigbee or Z-Wave stick pins the pod to one machine.
  Use a network-attached coordinator instead.
- **The cluster is now a dependency of the lights.** A Ceph rebalance that
  pauses I/O pauses Home Assistant with it.
