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
| Storage | 50Gi `rook-ceph-block` PVC, `ReadWriteOnce` |
| Database | CloudNativePG `Cluster` `nextcloud-db` |
| Secrets | `kv/nextcloud/config` in OpenBao |
| Files | [`nextcloud/`](https://github.com/JanWelker/homelab-apps/tree/main/nextcloud) |

## Configuration

The values in `nextcloud/application.yaml` that are not self-explanatory:

| Setting | Why |
| --- | --- |
| `internalDatabase.enabled: false`, `externalDatabase.existingSecret` | The bundled Bitnami subchart is replaced by a CloudNativePG `Cluster` at sync wave `-1`, per [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract). ArgoCD's health check for `Cluster` makes the wave wait for a working database before the chart's install job connects |
| `redis.enabled: false` | Another Bitnami subchart. One replica needs no shared cache; the chart configures APCu |
| `OVERWRITEPROTOCOL`, `OVERWRITEHOST`, `OVERWRITECLIURL`, `TRUSTED_PROXIES` in `extraEnv` | TLS terminates at the Gateway and requests arrive from Cilium's Envoy, so without these Nextcloud builds `http://` links and the login redirect loops. Env vars rather than a `proxy.config.php`: the image ships `reverse-proxy.config.php` reading exactly these, and config files load alphabetically, so a `proxy.config.php` of our own would lose |
| `strategy: Recreate`, `replicaCount: 1` | The data PVC is `ReadWriteOnce`; a `RollingUpdate` surges a pod that cannot mount it |
| Background jobs as a sidecar, not a `CronJob` | Same volume, same reason |
| `startupProbe` with `failureThreshold: 60` | Upgrades run database migrations at startup, longer than a liveness probe tolerates |
| `prometheus.serviceMonitor`, not `metrics.serviceMonitor` | The chart's values file documents the latter; the template reads the former. The wrong key renders nothing, silently. `metrics.enabled` does control the exporter |
| `nextcloud.openmetrics.allowedClients` | The default is k3s's CIDRs, which reject Prometheus while the ServiceMonitor looks healthy |
| `nextcloud.existingSecret` | Without it the chart writes `admin` / `changeme` into its own Secret and points the install and the exporter at it. Nothing fails at sync time; check the block is present on every values change |
| `allow_local_remote_servers`, set by the startup hook | `auth.k8s.wlkr.ch` resolves to the Gateway's private address and Nextcloud's SSRF guard rejects it (`violates local access rules`) while `curl` from the same container works. Lifting it applies to every outbound request; the compensating controls are the network policy and that federation and external storage are off. Pointing at the in-cluster Service instead would break the `iss` check |

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

The provider itself is `nextcloud/authentik-blueprint.yaml`, a ConfigMap
targeted at the `authentik` namespace, so provider and client change in one
commit. The platform mounts it as an optional projected volume, because this
arrives four stages after Authentik must be Healthy. The client credentials
stay in the platform repository (`make bao-secrets` generates them), so a
workload cannot take itself out from behind SSO on its own.

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
