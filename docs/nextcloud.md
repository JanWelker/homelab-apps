---
description: "Nextcloud on the cluster: the official chart, an external CloudNativePG database, and the two chart quirks that cost an afternoon."
---

# Nextcloud

[Nextcloud](https://nextcloud.com/) is the household's file storage, calendar
and contacts. It answers on [cloud.k8s.wlkr.ch](https://cloud.k8s.wlkr.ch), and
its manifests are in
[`nextcloud/`](https://github.com/JanWelker/homelab-apps/tree/main/nextcloud).

## The official chart

Nextcloud publishes its own Helm chart, from the Nextcloud organisation's own
repository at `https://nextcloud.github.io/helm/`. That makes this the
straightforward half of the pair: the chart is used, configured through
`valuesObject` in the Application, and the manifests it does not render — the
database, the `HTTPRoute`, the network policy, the admin `ExternalSecret` — come
from a second source pointing at this repository.

## The database is not the chart's

The chart bundles a Bitnami PostgreSQL subchart. It is disabled
(`internalDatabase.enabled: false`) in favour of a CloudNativePG `Cluster`, per
[the contract](https://janwelker.github.io/homelab/platform/cloudnative-pg/#the-contract).

The wiring is worth seeing once, because it is the same everywhere: CloudNativePG
writes a Secret named `nextcloud-db-app`, and the chart's `externalDatabase`
block reads the keys out of it by name.

```yaml
externalDatabase:
  enabled: true
  type: postgresql
  existingSecret:
    enabled: true
    secretName: nextcloud-db-app
    usernameKey: username
    passwordKey: password
    hostKey: host
    databaseKey: dbname
```

No password is written down. The `Cluster` is at sync wave `-1`, so ArgoCD —
which has a health check for `postgresql.cnpg.io/Cluster` — waits for a working
database before it applies the chart, whose install job connects immediately
and would otherwise fail the sync.

Redis is disabled for the same reason the database is: it is another Bitnami
subchart, and the chart's values already point it at `bitnamilegacy`. A single
replica does not need a shared cache, and the chart configures APCu for the
local one.

## Two chart quirks

Both of these render perfectly and do the wrong thing, which is the worst
failure mode a values file has.

!!! warning "The ServiceMonitor key is `prometheus.`, not `metrics.`"
    The chart's own values file documents the ServiceMonitor settings under `metrics.serviceMonitor`, with `@param metrics.serviceMonitor.enabled` in the comments — but the template reads `.Values.prometheus.serviceMonitor`. Setting the documented key renders nothing at all, silently, and the first sign of it is a dashboard with no data three weeks later. Both are set here; `metrics.enabled` really does control the exporter Deployment.

!!! warning "The openmetrics allow-list defaults to k3s"
    Nextcloud's built-in `/metrics` endpoint refuses clients outside
    `nextcloud.openmetrics.allowedClients`, and the chart's default is
    `10.42.0.0/16` and `10.43.0.0/16` — k3s's pod and service CIDRs. This
    cluster uses `10.244.0.0/16` and `10.96.0.0/12`, so the default would have
    rejected Prometheus while the ServiceMonitor reported itself perfectly
    healthy.

## Behind the Gateway

Nextcloud builds absolute URLs from what it believes the request scheme and
host were. Behind the `apps-gateway`, TLS is terminated before the request
arrives and the source address is Cilium's Envoy, so without help it produces
`http://` links on an `https://` site and the login redirect loops forever.

A `proxy.config.php` in the chart's `configs` block sets `trusted_proxies`,
`overwriteprotocol`, `overwritehost` and `overwrite.cli.url`. If the login page
ever starts looping again, this file is where to look first.

## One replica, one volume

The data PVC is `ReadWriteOnce`, so the deployment strategy is `Recreate` and
`replicaCount` is 1. A `RollingUpdate` would surge a second pod that cannot
mount the volume, and the rollout would sit there until the progress deadline
expired.

For the same reason the background-jobs container runs as a **sidecar** rather
than a `CronJob`: a separate cron pod would need the same `ReadWriteOnce`
volume, which only works while both happen to land on the same node.

Upgrades run Nextcloud's database migrations at startup, which takes it well
past a default liveness probe's patience — hence the startup probe with sixty
attempts. A major Nextcloud upgrade is legitimately slow; let it finish.

## The admin account

The initial admin credentials come from
[OpenBao](https://janwelker.github.io/homelab/platform/openbao/) through an
`ExternalSecret`, at `kv/nextcloud/config`. The `bao kv put` command that seeds
it is in the comment at the top of `nextcloud/secrets.yaml`, so a rebuilt
cluster does not require anyone to remember what the path was.

The metrics exporter authenticates as the same account, which is why it reads
the same Secret.

## Verifying

```bash
kubectl -n nextcloud get pods,pvc
kubectl -n nextcloud get cluster nextcloud-db
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- \
  php occ status
```

`occ` is the administrative CLI for everything the web UI does not expose —
including `occ maintenance:repair` and `occ db:add-missing-indices`, which
Nextcloud's own admin overview will eventually tell you to run.
