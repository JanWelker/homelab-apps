---
description: "The Shot Timer bridge on the cluster: watches the La Marzocco espresso machine through the La Marzocco cloud and starts the iPhone Live Activity through APNs."
---

# Shot Timer bridge

The bridge is the always-on half of the Shot Timer iPhone app. iOS will not
let an app hold the La Marzocco cloud websocket open in the background, so
this one process watches the machine, tracks each shot, looks up the
machine's exact extraction time afterwards, keeps the shot history in SQLite,
and starts and updates the phone's Live Activity through APNs. The phone and
watch apps call its small HTTP API. The source, the image and the chart live
in [somuch-cloud/shotapp](https://github.com/somuch-cloud/shotapp/tree/main/deploy); the
chart is published to `ghcr.io/janwelker/charts`, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [shot.k8s.wlkr.ch](https://shot.k8s.wlkr.ch/healthz), an API for the iPhone and watch apps |
| Authentication | The bridge's own bearer key; the apps cannot go through Authentik |
| Storage | PVC `shot-bridge`, SQLite and the La Marzocco installation key |
| Database | CloudNativePG `Cluster` `shot-bridge-db`, a primary and a streaming replica |
| Dials | `lion.lamarzocco.io`, APNs |
| Files | [`shot-bridge/`](https://github.com/JanWelker/homelab-apps/tree/main/shot-bridge) |

## State

| State | Where | Rebuildable? |
| --- | --- | --- |
| Shot history, registered phones, default dose, coffees, reference shots | PostgreSQL, the CloudNativePG `Cluster` `shot-bridge-db` (`database.yaml`) | History from its WAL archive, to any point inside its retention window; phones re-register on their next launch |
| The SQLite file from before 2026-10-19 | `bridge.db` on the PVC, read once by `migrate-sqlite` | Kept as a fallback; delete it once the PostgreSQL history has been checked |
| La Marzocco installation key | `installation_key.json` on the PVC | Yes, the bridge registers a new one on start |
| Account credentials and the APNs key | OpenBao `kv/shot-bridge/accounts` | Re-typed from the accounts |
| API key | OpenBao `kv/shot-bridge/config`, generated | Yes, then entered again in the iPhone app |

## Configuration

| Setting | Why |
| --- | --- |
| Own chart, values in `application.yaml` | The chart ships the Deployment, PVC, Service, `HTTPRoute` and `CiliumNetworkPolicy`; this directory adds the namespace and the secrets |
| One replica, `Recreate` | One cloud websocket; two copies would double every push |
| `database.existingSecret: shot-bridge-db-app` | The bridge reads `DATABASE_URL` from the Secret CloudNativePG writes for `shot-bridge-db` (`uri` key); without it the chart falls back to the SQLite file on the PVC. The PVC stays for the La Marzocco installation key |
| `Cluster` `shot-bridge-db`, two instances, 1Gi | A few rows a day, but the phones log every shot as it happens; a replica turns a drain or a node loss into a failover of seconds instead of a restart. `enablePDB: false` still, so the drain triggers that failover rather than hanging, and a topology spread keeps the two on different nodes. WAL and a nightly base backup through `backup.yaml` |
| `HTTPRoute` targets the bridge's Service | The phone sends `Authorization: Bearer`; an Authentik outpost in front would answer the app with a login page |
| Probes are TCP | `/healthz` returns 503 whenever the machine is off, and the apps still need the history then |
| `apns.env: sandbox` | The iPhone app is installed from Xcode with development signing; TestFlight builds need `production` |
| `apns.bundleId` and `apns.teamId` | Must match the app's bundle ID and team, or APNs rejects every push |
| `lm.serial` | The machine to watch; required since chart 0.1.4 |

### Network policy

The chart's `CiliumNetworkPolicy`, at sync wave `-2`. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy).

| Rule | Why |
| --- | --- |
| Ingress on 8080 from `ingress`, `host` and `remote-node` | The Gateway, and the kubelet's probes |
| Egress to `lion.lamarzocco.io` on 443 | The La Marzocco REST API and websocket |
| Egress to the four APNs names on 443, 2195 and 2196 | Pushes and broadcasts on 443; channel management on 2195 (sandbox) and 2196 (production) |
| Egress to the namespace on 5432 | The database's `-rw` Service |

### Secrets

| Path | Keys | Written by |
| --- | --- | --- |
| `kv/shot-bridge/accounts` | `lm-username`, `lm-password`, `apns-key-id`, `apns-key-p8` | `make bao-secrets` in the platform repository |
| `kv/shot-bridge/config` | `api-key` | The `PushSecret` in `secrets.yaml` |

The accounts path holds values from outside the cluster, so it is its own
path: a `bao kv put` replaces a path wholesale. `make bao-secrets` asks for
the La Marzocco login, then the APNs key ID and the path to the `.p8` file;
Enter leaves the APNs half empty until the key exists.

## Usage

Read the API key and enter it with `https://shot.k8s.wlkr.ch` in the iPhone
app's setup screen; **Test** shows the machine's state.

```bash
kubectl -n shot-bridge get secret shot-bridge -o jsonpath='{.data.BRIDGE_API_KEY}' | base64 -d
```

## Health check

```bash
kubectl -n shot-bridge get pods,externalsecret,httproute
curl -s https://shot.k8s.wlkr.ch/healthz    # 200 while the machine is reachable, 503 while it is off
kubectl -n shot-bridge logs deploy/shot-bridge
```

## Pitfalls

- **The image and chart have to be public on GHCR.** The cluster has no pull
  secret for `ghcr.io/janwelker`, and ArgoCD has no credentials for the chart
  registry.
- **The sync stops at wave `-1` until `kv/shot-bridge/accounts` exists.** The
  `ExternalSecret` fails on a missing path, so the Deployment is never
  created; run `make bao-secrets`.
- **The pod crash-loops while the APNs keys are empty.** The bridge exits on a
  missing variable rather than starting half-configured.
- **A changed API key logs the phone out.** Enter the new one in the app's
  setup screen; the watch receives it from the phone.
