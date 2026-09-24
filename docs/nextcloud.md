---
description: "Nextcloud on the cluster: the official chart, an external CloudNativePG database, Authentik OIDC, and the chart values that render fine and do the wrong thing."
---

# Nextcloud

[Nextcloud](https://nextcloud.com/) is the household's file storage, calendar
and contacts. It uses Nextcloud's own Helm chart, configured through
`valuesObject`; the manifests the chart does not render (the database, the
`HTTPRoute`, the network policy, the `ExternalSecret`s, the Authentik
blueprint) come from a second source pointing at this repository.

## At a glance

| | |
| --- | --- |
| URL | [cloud.k8s.wlkr.ch](https://cloud.k8s.wlkr.ch) |
| Authentication | Authentik OIDC through the first-party `user_oidc` app; local login hidden |
| Chart | `nextcloud`, from `https://nextcloud.github.io/helm/` |
| Storage | `rook-ceph-block` PVC, `ReadWriteOnce` |
| Database | CloudNativePG `Cluster` `nextcloud-db` |
| Secrets | `kv/nextcloud/config` in OpenBao |
| Files | [`nextcloud/`](https://github.com/JanWelker/homelab-apps/tree/main/nextcloud) |

## Configuration

The values in `nextcloud/application.yaml` that are not self-explanatory:

| Setting | Why |
| --- | --- |
| `podSecurityContext` and `securityContext` set seccomp only; the namespace enforces `baseline` | The apache flavour of the official image starts as root and drops to `www-data` itself, so `runAsNonRoot` and a read-only root would mean changing how the image runs. `RuntimeDefault` is the profile the image is built for. The metrics exporter is a static Go binary that writes nothing, so it runs fully restricted |
| `internalDatabase.enabled: false`, `externalDatabase.existingSecret` | `internalDatabase` is the chart's SQLite; its Bitnami PostgreSQL subchart is `postgresql.enabled`, off by default. Both give way to a CloudNativePG `Cluster` at sync wave `-1`, per [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract). ArgoCD's health check for `Cluster` makes the wave wait for a working database before the chart's install job connects |
| `redis.enabled: false` | Another Bitnami subchart. One replica needs no shared cache; the chart configures APCu |
| `OVERWRITEPROTOCOL`, `OVERWRITEHOST`, `OVERWRITECLIURL`, `TRUSTED_PROXIES` in `extraEnv` | TLS terminates at the Gateway and requests arrive from Cilium's Envoy, so without these Nextcloud builds `http://` links and the login redirect loops. Env vars rather than a `proxy.config.php`: the image ships `reverse-proxy.config.php` reading exactly these, and config files load alphabetically, so a `proxy.config.php` of our own would lose |
| `strategy: Recreate`, `replicaCount: 1` | The data PVC is `ReadWriteOnce`; a `RollingUpdate` surges a pod that cannot mount it |
| Background jobs as a sidecar, not a `CronJob` | Same volume, same reason |
| `startupProbe` with a long `failureThreshold` | Upgrades run database migrations at startup, longer than a liveness probe tolerates |
| `prometheus.serviceMonitor`, not `metrics.serviceMonitor` | The chart's values file documents the latter; the template reads the former. The wrong key renders nothing, silently. `metrics.enabled` does control the exporter |
| `nextcloud.openmetrics.allowedClients` | Nextcloud's `/metrics` refuses clients outside this list, and the chart's default is k3s's CIDRs, which reject Prometheus with a 403 while the ServiceMonitor looks healthy. The pod and service CIDRs are in `ansible/inventory.yaml` in the platform repository. Setting the value only renders an environment variable: the chart mounts the config file that reads it only when `nextcloud.configs` is non-empty ([nextcloud/helm#887](https://github.com/nextcloud/helm/issues/887)), so the startup hook applies it with `occ` instead, deleting the key first because `config:system:set` addresses array elements by index and never shortens a list |
| `nextcloud.existingSecret` | Without it the chart writes `admin` / `changeme` into its own Secret and points the install and the exporter at it. Nothing fails at sync time and nothing renders differently; the only sign is an exporter that cannot log in. Check the block is present on every values change |
| `allow_local_remote_servers`, set by the startup hook | `auth.k8s.wlkr.ch` resolves to the Gateway's private address and Nextcloud's SSRF guard rejects it (`violates local access rules`) while `curl` from the same container works. Lifting it applies to every outbound request; the compensating controls are the egress half of `networkpolicy.yaml`, which names the only hosts the web pod may reach, and that federation and external storage are off. Pointing at the in-cluster Service instead would break the `iss` check |

### Network policy

Every rule in `nextcloud/networkpolicy.yaml`, and why it is there. The shape
is [Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy).

| Rule | Why |
| --- | --- |
| Ingress from `ingress` on 80 | The Gateway reaches the web pod directly; Nextcloud handles its own login |
| Ingress from Prometheus on 80, 9205 and 9187 | Nextcloud's own `/metrics`, the exporter, and the database's metrics |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager's status endpoint; without it the `Cluster` never goes Healthy. See [Sync stuck on the database](#sync-stuck-on-the-database) |
| Egress from the web pod to the Authentik server pods on 9000 | Logins go to `auth.k8s.wlkr.ch`, which resolves to the Gateway's own address and is `world` to Cilium. The Gateway's Envoy then checks this policy against the Authentik pod it picks and answers 403 itself when that pod is not listed, so both the name and the pod are allowed |
| Egress from the web pod to `*.nextcloud.com` | The app store, update notifications and the announcement feed |
| Egress from the web pod to `github.com` and `release-assets.githubusercontent.com` | Every app, `user_oidc` included, is a GitHub release asset that redirects to the second host. Without both, the startup hook cannot install it on a fresh volume |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

With `allow_local_remote_servers` on, this list is the control that says where
an outbound request may go.

The database wiring, the same for every application here:

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

## Usage

### OIDC

A `before-starting` hook configures `user_oidc` on every start, after any
install or upgrade, so one hook covers both and re-asserts the configuration
if someone changes it in the UI. Every command is idempotent:

```sh
php occ app:install user_oidc || php occ app:enable user_oidc
php occ user_oidc:provider Authentik \
  --clientid="$NEXTCLOUD_OIDC_CLIENT_ID" \
  --clientsecret="$NEXTCLOUD_OIDC_CLIENT_SECRET" \
  --discoveryuri="https://auth.k8s.wlkr.ch/application/o/nextcloud/.well-known/openid-configuration" \
  ...
php occ config:system:set hide_login_form --type boolean --value true
```

The `user_oidc:provider` call is not fatal: blueprint discovery is
asynchronous, so on a first deploy the provider may not exist yet. The login
form stays visible, the pod logs a warning, and the next restart configures it.

Two details of that call:

- `--unique-uid=0` makes the Nextcloud user ID the raw `preferred_username`
  claim, so an Authentik user named like the local admin logs in as that
  admin. Acceptable only while one person hands out Authentik usernames.
- `user_oidc:provider` never fetches the discovery document, so its exit code
  says nothing about whether the provider exists. Hiding the login form on that
  exit code locks everyone out behind a button that 404s. The hook fetches the
  discovery URL itself and hides the form only when it answers with an issuer;
  the `false` branch brings the form back if a working login later stops
  working. When it warns, check that Authentik's worker has the `NEXTCLOUD_*`
  environment variables: `envFrom` injects them at pod start, so a Secret
  updated later needs a worker restart.

The provider itself is `nextcloud/authentik-blueprint.yaml`, a ConfigMap
targeted at the `authentik` namespace, so provider and client change in one
commit. The platform mounts it as an optional projected volume, because a fresh
cluster has Authentik before it has any workload, and discovers it on the
worker's startup, hourly, and through a file watcher. The ConfigMap sits at
sync wave `-1` so the provider usually exists before the hook runs; discovery
is asynchronous, so that is a head start, not a guarantee. The client
credentials stay in the platform repository (`make bao-secrets` generates
them), so a workload cannot take itself out from behind SSO on its own. The
outpost's provider list stays there too: that entry replaces one global object,
and two repositories writing it would overwrite each other's applications.

| Blueprint field | Why |
| --- | --- |
| `grant_types` listed explicitly | An empty list serves no grants and rejects every login |
| `redirect_uris` ends in `/apps/user_oidc/code` | `user_oidc` builds the path from the provider name it is given |
| `client_id` and `client_secret` from `!Env` | Authentik reads them from its own `ExternalSecret` on `kv/nextcloud/config`, the same pair Nextcloud reads |

Use `auth.k8s.wlkr.ch`, never `auth.infra.k8s.wlkr.ch`: the `*.infra` zone
resolves only on the local network, and a client must use one name
consistently or the `iss` claim fails. See
[Two hostnames](https://homelab.wlkr.ch/platform/authentik/#two-hostnames).

### Secrets

`kv/nextcloud/config` holds four values, generated by `make bao-secrets` in the
platform repository. It is its own path rather than keys under
`kv/authentik/config` because a `bao kv put` replaces a path wholesale.

| Key | Read by |
| --- | --- |
| `username`, `password` | Nextcloud, as the break-glass admin; the metrics exporter authenticates as it too |
| `oidc-client-id`, `oidc-client-secret` | Nextcloud **and** Authentik, through two `ExternalSecret`s |

Both `ExternalSecret`s sit at sync wave `-1`, with the database and ahead of
the chart that reads them, and keep their Secret when deleted
(`deletionPolicy: Retain`): the account survives, but the Secret is the only
copy of the password outside OpenBao. The database password is not here;
CloudNativePG generates it and nothing outside the cluster needs it.

### Break-glass

`hide_login_form` hides the fields; it does not disable local accounts. The
admin from `make bao-secrets` still works at:

```text
https://cloud.k8s.wlkr.ch/login?direct=1
```

Same reasoning as
[Grafana's break-glass admin](https://homelab.wlkr.ch/platform/authentik/#when-authentik-is-down).

## Health check

```bash
kubectl -n nextcloud get pods,pvc
kubectl -n nextcloud get cluster nextcloud-db
kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- php occ status
```

`occ` is the administrative CLI, including `occ maintenance:repair` and
`occ db:add-missing-indices`, which the admin overview will eventually ask for.

## Pitfalls

### Sync stuck on the database

The default-deny policy must allow the `cnpg-system` namespace to reach the
database pod on port 8000, the instance manager's status endpoint the operator
polls, and the policy must sit at sync wave `-2` with the namespace. At the
default wave it lands after the `Cluster` at `-1`, and a wave that never
finishes never applies the rule that would unblock it.

1. **Symptom.** Postgres serves the application and `kubectl get cluster`
   reads `1/1`, but the phase is `Instance Status Extraction Error: HTTP
   communication issue`. The Application is `Synced` with health `Unknown` and
   every entry in `status.resources` lacks a health field: a genuinely
   unhealthy workload names the failing resource.

    ```text
    $ kubectl get application -n argocd nextcloud -o jsonpath='{.status.operationState.message}'
    waiting for healthy state of postgresql.cnpg.io/Cluster/nextcloud-db
    ```

2. **Confirm the drop** from the node running the database:

    ```bash
    kubectl exec -n kube-system <cilium-pod-on-that-node> -c cilium-agent -- \
      hubble observe --verdict DROPPED --from-namespace cnpg-system --last 20
    ```

3. **Check which waves ran.** If `CiliumNetworkPolicy` is missing while
   `Cluster` reads `Running`, the policy is behind the thing it should unblock:

    ```bash
    kubectl get application -n argocd nextcloud \
      -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.kind}{"\t"}{.hookPhase}{"\n"}{end}'
    ```

4. **Fix.** Put the policy at wave `-2`, then terminate the stuck operation.
   The next sync applies the policy first and the `Cluster` goes Healthy.
