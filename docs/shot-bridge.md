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
in [tcinbis/shotapp](https://github.com/tcinbis/shotapp/tree/main/deploy); the
chart is published to `ghcr.io/janwelker/charts`, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [shot.k8s.wlkr.ch](https://shot.k8s.wlkr.ch/healthz), an API for the iPhone and watch apps |
| Authentication | The bridge's own bearer key; the apps cannot go through Authentik |
| Storage | PVC `shot-bridge`, SQLite and the La Marzocco installation key |
| Database | None; SQLite on the PVC |
| Dials | `lion.lamarzocco.io`, APNs |
| Files | [`shot-bridge/`](https://github.com/JanWelker/homelab-apps/tree/main/shot-bridge) |

## State

| State | Where | Rebuildable? |
| --- | --- | --- |
| Shot history, registered phones, default dose | SQLite on the PVC | History no; phones re-register on their next launch |
| La Marzocco installation key | `installation_key.json` on the PVC | Yes, the bridge registers a new one on start |
| Account credentials and the APNs key | OpenBao `kv/shot-bridge/accounts` | Re-typed from the accounts |
| API key | OpenBao `kv/shot-bridge/config`, generated | Yes, then entered again in the iPhone app |

## Configuration

| Setting | Why |
| --- | --- |
| Own chart, values in `application.yaml` | The chart ships the Deployment, PVC, Service, `HTTPRoute` and `CiliumNetworkPolicy`; this directory adds the namespace and the secrets |
| One replica, `Recreate` | One cloud websocket and one SQLite file; two copies would double every push |
| SQLite, not a CloudNativePG `Cluster` | One writer and a few rows a day; the bridge is built around SQLite, and Velero backs up the PVC |
| `HTTPRoute` targets the bridge's Service | The phone sends `Authorization: Bearer`; an Authentik outpost in front would answer the app with a login page |
| Probes are TCP | `/healthz` returns 503 whenever the machine is off, and the apps still need the history then |
| `apns.env: sandbox` | The iPhone app is installed from Xcode with development signing; TestFlight builds need `production` |
| `apns.bundleId` and `apns.teamId` | Must match the app's bundle ID and team, or APNs rejects every push |
| `lm.serial` | The machine to watch; the bridge's built-in default is one specific Micra |

### Network policy

The chart's `CiliumNetworkPolicy`, at sync wave `-2`. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy).

| Rule | Why |
| --- | --- |
| Ingress on 8080 from `ingress`, `host` and `remote-node` | The Gateway, and the kubelet's probes |
| Egress to `lion.lamarzocco.io` on 443 | The La Marzocco REST API and websocket |
| Egress to the four APNs names on 443, 2195 and 2196 | Pushes and broadcasts on 443; channel management on 2195 (sandbox) and 2196 (production) |

### Secrets

| Path | Keys | Written by |
| --- | --- | --- |
| `kv/shot-bridge/accounts` | `lm-username`, `lm-password`, `apns-key-id`, `apns-key-p8` | Typed in by hand, see below |
| `kv/shot-bridge/config` | `api-key` | The `PushSecret` in `secrets.yaml` |

The accounts path holds values from outside the cluster, so it is its own
path: a `bao kv put` replaces a path wholesale.

```bash
bao kv put kv/shot-bridge/accounts \
  lm-username=... lm-password=... apns-key-id=... apns-key-p8=@AuthKey.p8
```

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
- **The pod crash-loops until `kv/shot-bridge/accounts` exists.** The bridge
  exits on a missing variable rather than starting half-configured.
- **A changed API key logs the phone out.** Enter the new one in the app's
  setup screen; the watch receives it from the phone.
