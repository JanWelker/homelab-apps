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

### The operator needs ingress to the instance

The default-deny policy has to allow the `cnpg-system` namespace to reach the
database pod on port 8000. That is the instance manager's status endpoint, which
the CloudNativePG operator polls to decide what the `Cluster` is doing.

Miss it and nothing looks broken where you would look first. Postgres starts,
accepts connections and serves the application; `kubectl get cluster` reports
`1/1` ready and a healthy PVC. But the phase reads
`Instance Status Extraction Error: HTTP communication issue`, so the `Cluster`
never goes Healthy, so the sync operation started at wave `-1` never finishes:

```text
$ kubectl get application -n argocd nextcloud -o jsonpath='{.status.operationState.message}'
waiting for healthy state of postgresql.cnpg.io/Cluster/nextcloud-db
```

The Application then sits at `Synced` with health `Unknown` and **every** resource
in `status.resources` missing its health field, because the controller never got
to assess them. Unknown-with-no-resource-health is the signature: a genuinely
unhealthy workload names the resource that is failing.

Confirm it from the node running the database, where the policy is enforced:

```bash
kubectl exec -n kube-system <cilium-pod-on-that-node> -c cilium-agent -- \
  hubble observe --verdict DROPPED --from-namespace cnpg-system --last 20
```

A dropped `SYN` to `:8000` is the whole story.

### The policy has to land before the database

Adding that rule is not enough on its own. The policy sits at sync wave `-2`,
with the namespace, and it has to: at the default wave it would be applied
*after* the `Cluster` at `-1`, and wave `-1` never finishes, so wave `0` never
runs, so the rule that would end the wait never reaches the cluster. The repair
commits itself to Git and then sits there, correct and unapplied, while
`argocd app get nextcloud` keeps reporting the same stuck operation.

The tell is the applied-resource list. A sync parked at wave `-1` shows only the
waves that ran:

```bash
kubectl get application -n argocd nextcloud \
  -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.kind}{"\t"}{.hookPhase}{"\n"}{end}'
```

If the `CiliumNetworkPolicy` is missing from that list while `Cluster` reads
`Running`, the policy is behind the thing it is meant to unblock — no amount of
re-syncing fixes it, because every attempt stops at the same wave. Terminate the
stuck operation once the wave is corrected; the next sync applies the policy
first and the `Cluster` goes Healthy on its own.

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

## Authentik, not Nextcloud's own accounts

Nextcloud's `user_oidc` app is first-party — it is in the `nextcloud` GitHub
organisation — so this is real single sign-on rather than a proxy bolted in
front. A `before-starting` hook in the chart configures it:

```sh
php occ app:install user_oidc || php occ app:enable user_oidc
php occ user_oidc:provider Authentik \
  --clientid="$NEXTCLOUD_OIDC_CLIENT_ID" \
  --clientsecret="$NEXTCLOUD_OIDC_CLIENT_SECRET" \
  --discoveryuri="https://auth.k8s.wlkr.ch/application/o/nextcloud/.well-known/openid-configuration" \
  ...
php occ config:system:set hide_login_form --type boolean --value true
```

`before-starting` is the last hook the image runs and it runs on **every**
start, after an install or an upgrade has finished — so one hook covers both
cases and re-asserts the configuration if somebody changes it in the UI. Every
command is idempotent: `app:install` is a no-op once installed, and
`user_oidc:provider` updates the provider of that name rather than adding a
second one.

### The provider is defined here too

`nextcloud/authentik-blueprint.yaml` is a ConfigMap targeted at the `authentik`
namespace, holding the `oauth2provider` and the Authentik application. So the
provider and the client that authenticates against it change in one commit,
rather than one commit per repository.

The platform mounts it into Authentik's worker as an **optional** projected
volume — optional because this arrives in `12-workloads`, four stages after
Authentik has to be Healthy, and a required mount would have the worker waiting
for a stage that is waiting for the worker.

Two things stay in the platform repository, and both are deliberate: the client
credentials, which `bao-secrets.sh` generates into `kv/nextcloud/config` — a
workload cannot mint its own, which is what keeps SSO onboarding a two-repository
act — and the embedded outpost's provider list, which is one global object that
two repositories writing would overwrite.

!!! warning "Discovery is asynchronous, so the hook tolerates its absence"
    `blueprints_discovery` runs on the worker's startup, hourly, and on a file watcher — so on a first deploy the hook above can run before the provider exists. The `user_oidc:provider` call is therefore **not** fatal: if it fails, the login form stays visible, a warning goes to the pod log, and the next restart configures it. A Nextcloud that will not start is a much worse outcome than one that is up with the local login still working.

!!! danger "Nextcloud blocks its own HTTP client from reaching private IPs"
    `auth.k8s.wlkr.ch` is the apps Gateway, `10.9.2.249`. Nextcloud's SSRF guard rejects that outright — `Host "10.9.2.249" (auth.k8s.wlkr.ch:80) violates local access rules` — so every discovery fetch failed with *"Could not reach the OpenID Connect provider"* while `curl` from the same container worked perfectly, because `curl` never goes through that guard. The hook sets `allow_local_remote_servers` to lift it. That is a genuine reduction in defence in depth, applying to **every** outbound request Nextcloud makes; the compensating controls are the namespace's `CiliumNetworkPolicy` and the fact that federation and external storage are not enabled. Pointing user_oidc at the in-cluster Service instead would dodge the guard and break the issuer check, since the browser and the server would then discover different issuers.

!!! warning "The hostname is `auth.k8s.wlkr.ch`, not `auth.infra...`"
    The `*.infra` zone resolves only on the local network. A discovery URI pointing there would work from the sofa and hang from anywhere else, because the browser would be redirected to an authorize endpoint that does not resolve. Authentik answers on both names and builds every OIDC URL from the one the request arrived on — but a client must use one of them consistently, or the `iss` claim fails the check against the issuer it discovered.

### Break-glass

`hide_login_form` hides the username and password fields; it does not disable
the local accounts. The admin generated by `make bao-secrets` still works, at:

```text
https://cloud.k8s.wlkr.ch/login?direct=1
```

That is the way back in on the day Authentik is the thing that is broken. Same
reasoning as [Grafana's break-glass
admin](https://janwelker.github.io/homelab/platform/authentik/#when-authentik-is-down);
ArgoCD takes the stricter line and disables its local admin outright.

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

## Secrets

All four values live in `kv/nextcloud/config` in
[OpenBao](https://janwelker.github.io/homelab/platform/openbao/), generated by
`make bao-secrets` in the platform repository:

| Key | Read by |
| --- | --- |
| `username`, `password` | Nextcloud, as the break-glass admin; the metrics exporter authenticates as it too |
| `oidc-client-id`, `oidc-client-secret` | Nextcloud **and** Authentik, through two `ExternalSecret`s |

It is deliberately its own path rather than four more keys under
`kv/authentik/config`. A `bao kv put` replaces a path wholesale, so every
application keeping its client credentials there would make adding the next one
an Authentik outage.

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
