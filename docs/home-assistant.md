---
description: "Home Assistant on the cluster: why it is plain manifests rather than a chart, where its two kinds of state live, and what home automation gives up by running in Kubernetes."
---

# Home Assistant

[Home Assistant](https://www.home-assistant.io/) runs the house — lights,
sensors, climate, and whatever else has been added since this page was written.
It answers on [home.k8s.wlkr.ch](https://home.k8s.wlkr.ch), and its manifests
are in [`home-assistant/`](https://github.com/JanWelker/homelab-apps/tree/main/home-assistant).

## Plain manifests, not a chart

Home Assistant publishes no official Helm chart. The community ones are
third-party repackagers, and the rule here is that a version pin is only worth
having when you know who published the thing you pinned — so this is a
Deployment, a Service, a PVC and a ConfigMap, written out. See
[Conventions &rarr; Official upstream sources only](conventions.md#2-official-upstream-sources-only).

That turned out to be the smaller amount of work. Home Assistant is a single
stateful process with one volume and one port; almost everything a chart would
parameterise has exactly one correct value here.

## Two kinds of state, in two places

This is the part worth understanding before touching anything:

| State | Where | Rebuildable? |
| --- | --- | --- |
| Registries, users, tokens, integration config (`/config/.storage`) | The `home-assistant-config` PVC | **No.** Losing it means re-pairing every device |
| History and long-term statistics | PostgreSQL, via CloudNativePG | Only from a backup; losing it loses your graphs |
| `configuration.yaml` | A ConfigMap, in Git | Yes, it is the file in the repository |

The split matters because the recorder database is the part that grows without
bound and the `/config` volume is the part that cannot be reconstructed. They
are sized and backed up accordingly, and 5Gi of `/config` is generous for what
is mostly JSON.

### The recorder is not SQLite

Home Assistant's default recorder is SQLite in a file on `/config`. On a
network block device — which is what every PVC here is — SQLite's locking
behaviour is the single most common cause of a Home Assistant that feels slow
for no visible reason.

So the recorder points at a CloudNativePG `Cluster` instead, per [the
contract](https://janwelker.github.io/homelab/platform/cloudnative-pg/#the-contract).
`purge_keep_days` is set to 42; the default of 10 is reliably shorter than the
moment you go looking for a graph.

!!! warning "`secrets.yaml` is generated, not yours"
    Home Assistant removed its `!env_var` YAML tag years ago, so there is no way to put an environment variable into `configuration.yaml`. The database URL reaches it through `!secret` instead, and an init container writes `/config/secrets.yaml` from CloudNativePG's Secret on **every** start — so anything added to that file by hand is lost at the next restart. A secret a workload needs belongs in [OpenBao](https://janwelker.github.io/homelab/platform/openbao/) and reaches the pod as an environment variable or a mounted file.

### Restarting after a config change

The ConfigMap is mounted over `/config/configuration.yaml`, and Home Assistant
reads it once, at startup. Merging a change to it does nothing visible until
the pod restarts:

```bash
kubectl -n home-assistant rollout restart deploy/home-assistant
```

The UI's own "restart" button does the same thing from inside.

## Behind the Gateway

Requests arrive from Cilium's Envoy, not from the client, so
`configuration.yaml` sets `use_x_forwarded_for` with the pod CIDR in
`trusted_proxies`. Without it, Home Assistant sees every request as coming from
one address: the ban list becomes useless and rate limiting counts the whole
household as one user.

## What this costs

Running home automation on a Kubernetes cluster has two real drawbacks, and
both are accepted rather than solved:

- **No local device discovery.** mDNS and SSDP need host networking, which
  needs a `privileged` namespace, and that is a bad trade for a convenience.
  Devices that cannot be added by IP address have to be added through an
  integration that does not rely on broadcast discovery.
- **No USB devices.** A Zigbee or Z-Wave stick is plugged into one specific
  machine, and a pod that requires that machine is a pod that cannot be
  rescheduled. Anything of that kind belongs on a network-attached coordinator
  the pod can reach over IP.

There is also a third, less obvious one: the cluster is now a dependency of the
lights working. A Ceph rebalance that pauses I/O pauses Home Assistant with it.
That is the trade for having it backed up, monitored and reproducible, and it
is worth knowing before the first time it happens.

## Verifying

```bash
kubectl -n home-assistant get pods,pvc
kubectl -n home-assistant get cluster home-assistant-db
```

The database should report `Cluster in healthy state`. If the application pod
is in `Init`, it is waiting on that: the init container cannot write
`secrets.yaml` until CloudNativePG has produced the Secret it reads.
