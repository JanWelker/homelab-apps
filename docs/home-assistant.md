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

## Behind the Gateway, and behind Authentik

`home.k8s.wlkr.ch` does **not** route to Home Assistant. It routes to
Authentik's embedded outpost, which authenticates the request and only then
forwards it to `home-assistant.home-assistant.svc:8123`.

This is the one proxied application in the cluster that has a login of its own.
Everything else behind the outpost — Hubble, the Ceph dashboard, Prometheus,
Alertmanager — has no authentication whatsoever, which is what makes the
outpost *the* authentication rather than an extra one. Home Assistant is
different because upstream ships no OIDC provider at all: the only auth
providers in the codebase are `homeassistant`, `command_line`,
`trusted_networks` and an example marked insecure.

So browser users log in twice, deliberately. That is defence in depth, not
single sign-on, and it is worth being clear about which one you are getting.

!!! warning "The API is not behind Authentik"
    The companion apps and every webhook authenticate with a long-lived token and cannot complete an interactive Authentik login, so `skip_path_regex` on the provider lets `/api/`, `/auth/token` and the external-auth callback through untouched. **Home Assistant's own accounts are the only thing guarding those paths.** Revoking someone's Authentik account does not revoke their Home Assistant token — that has to be done in Home Assistant, under Settings → People.

Gating those paths was the alternative, and it would not have made the API
safer. It would have stopped the phones working and pushed the whole thing
towards being exposed some other way, which is how a security control becomes
the reason for a worse setup.

### Why the network policy mentions the cnpg-system namespace

The policy allows `cnpg-system` to reach the database pod on port 8000, the
instance manager's status endpoint that the CloudNativePG operator polls.

Without that rule the failure is quiet in the worst way. Postgres runs, the
recorder writes to it, and `kubectl get cluster` says `1/1` ready — but the phase
reads `Instance Status Extraction Error: HTTP communication issue`, the `Cluster`
never goes Healthy, and the sync operation waiting on it at wave `-1` never
completes. The Application reports `Synced` with health `Unknown`, and every
entry in `status.resources` is missing its health field because the controller
never assessed them. That combination — Unknown with no resource naming itself —
is what distinguishes this from an actually unhealthy workload.

The policy therefore sits at sync wave `-2`, with the namespace. At the default
wave it would be applied after the `Cluster` at `-1` — and that is exactly the
wave stuck waiting, so the rule that would release it never gets applied.
Writing the rule and leaving the wave alone changes nothing in the cluster.

The same rule is on the Nextcloud policy for the same reason; that page has [the
hubble command](nextcloud.md#the-operator-needs-ingress-to-the-instance) for
confirming the drop and [the wave
trap](nextcloud.md#the-policy-has-to-land-before-the-database) in full.

### Why the network policy mentions the authentik namespace

Because that is where the traffic comes from. The `CiliumNetworkPolicy` admits
port 8123 from the `authentik` namespace rather than from the Gateway, and
`fromEntities: ingress` is deliberately absent — a request that reaches Home
Assistant straight from the Gateway would have skipped the authentication
layer entirely.

### Trusted proxies

Requests arrive from Cilium's Envoy and then the outpost, not from the client,
so `configuration.yaml` sets `use_x_forwarded_for` with the pod CIDR in
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
