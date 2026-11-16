# Shot Timer bridge

The bridge is the always-on half of the Shot Timer iPhone app. iOS will not let an app hold the La Marzocco cloud websocket open in the background, so this one process watches the machine, tracks each shot, looks up the machine's exact extraction time afterwards, keeps the shot history in SQLite, and starts and updates the phone's Live Activity through APNs. The phone and watch apps call its small HTTP API. The source, the image and the chart live in [somuch-cloud/extractor.cafe](<https://github.com/somuch-cloud/extractor.cafe/tree/main/deploy>); the chart is published to `ghcr.io/somuch-cloud/charts`, per [Conventions → Official upstream sources only](<https://homelab-apps.wlkr.ch/conventions/#2-official-upstream-sources-only>).

## At a glance

|  |  |
| --- | --- |
| URL | [shot.k8s.wlkr.ch](<https://shot.k8s.wlkr.ch/healthz>), an API for the iPhone and watch apps |
| Authentication | The bridge's own bearer key; the apps cannot go through Authentik |
| Storage | PVC `shot-bridge`, SQLite and the La Marzocco installation key |
| Database | CloudNativePG `Cluster` `shot-bridge-db`, a primary and a streaming replica |
| Dials | `lion.lamarzocco.io`, APNs |
| Files | [`shot-bridge/`](<https://github.com/JanWelker/homelab-apps/tree/main/shot-bridge>) |

## State

| State | Where | Rebuildable? |
| --- | --- | --- |
| Shot history, registered phones, default dose, coffees, reference shots | PostgreSQL, the CloudNativePG `Cluster` `shot-bridge-db` (`database.yaml`) | History from its WAL archive, to any point inside its retention window; phones re-register on their next launch |
| La Marzocco installation key | `installation_key.json` on the PVC | Yes, the bridge registers a new one on start |
| Account credentials and the APNs key | OpenBao `kv/shot-bridge/accounts` | Re-typed from the accounts |
| API key | OpenBao `kv/shot-bridge/config`, generated | Yes, then entered again in the iPhone app |

## Configuration

| Setting | Why |
| --- | --- |
| Own chart, values in `application.yaml` | The chart ships the Deployment, PVC, Service, `HTTPRoute` and the bridge's `CiliumNetworkPolicy`; this directory adds the namespace, the secrets and the namespace's default-deny policies in `networkpolicy.yaml`, which are what police the database pods |
| One replica, `Recreate` | One cloud websocket; two copies would double every push |
| `database.existingSecret: shot-bridge-db-app` | The bridge reads `DATABASE_URL` from the Secret CloudNativePG writes for `shot-bridge-db` (`uri` key); without it the chart falls back to the SQLite file on the PVC. The PVC stays for the La Marzocco installation key |
| `Cluster` `shot-bridge-db`, two instances, 1Gi | A few rows a day, but the phones log every shot as it happens; a replica turns a drain or a node loss into a failover of seconds instead of a restart. `enablePDB: false` still, so the drain triggers that failover rather than hanging, and a topology spread keeps the two on different nodes. WAL and a nightly base backup through `backup.yaml` |
| `HTTPRoute` targets the bridge's Service | The phone sends `Authorization: Bearer`; an Authentik outpost in front would answer the app with a login page |
| Probes are TCP | `/healthz` returns 503 whenever the machine is off, and the apps still need the history then |
| `apns.env: sandbox` | The iPhone app is installed from Xcode with development signing; TestFlight builds need `production` |
| `apns.bundleId` and `apns.teamId` | Must match the app's bundle ID and team, or APNs rejects every push |
| `lm.serial` | The machine to watch; the chart requires it |
| `admin.enabled: true` | The [admin UI](<https://homelab-apps.wlkr.ch/extractor-admin/index.md>)'s read-only token, and its pods let in on 8080 |
| `timeZone: Europe/Zurich` | The bridge dates a bag's opening by the day of its first shot; the image runs in UTC otherwise, so a shot before 01:00 or 02:00 would land on the day before |

### Network policy

The chart's `CiliumNetworkPolicy` selects the bridge's pod; the `default-ingress`, `default-egress` and `database` policies in `networkpolicy.yaml` select the whole namespace, so the database pods are default-deny too. All at sync wave `-2`. The shape is [Conventions → Ship a `CiliumNetworkPolicy`](<https://homelab-apps.wlkr.ch/conventions/#5-ship-a-ciliumnetworkpolicy>).

| File | Rule | Why |
| --- | --- | --- |
| Chart | Ingress on 8080 from `ingress` and `host` | The Gateway, and the kubelet's probes; the chart admits `host` alone where the namespace policies below admit `remote-node` too |
| Chart | Ingress on 8080 from the admin UI's pods | `admin.enabled`; the [admin UI](<https://homelab-apps.wlkr.ch/extractor-admin/index.md>) reads with its token |
| Chart | Egress to `lion.lamarzocco.io` on 443 | The La Marzocco REST API and websocket |
| Chart | Egress to the Kaffeemacher shop and `cdn.shopify.com` on 443 | The coffee catalog and the bag photos |
| Chart | Egress to the four APNs names on 443, 2195 and 2196 | Pushes and broadcasts on 443; channel management on 2195 (sandbox) and 2196 (production) |
| Chart | Egress to the namespace on `database.port` | The database's `-rw` Service, rendered because `database.existingSecret` is set |
| Chart | Egress to `kube-dns` on 53 | The chart's own DNS rule; the platform's cluster-wide rule grants the same, so it adds nothing here |
| `networkpolicy.yaml` | Ingress from the namespace, from `host` and `remote-node`; egress to the namespace | The rules every policy carries, here for the database pods too: [What every policy contains](<https://homelab.wlkr.ch/platform/security-policies/#what-every-policy-contains>); the replica streams from the primary through them |
| `networkpolicy.yaml` | Ingress from Prometheus on 9187, `GET /metrics` only | The database's exporter, through its `PodMonitor`; the bridge exposes no metrics |
| `networkpolicy.yaml` | Ingress from `cnpg-system` on 8000 | The operator reads the instance manager's status; without it the `Cluster` never goes Healthy |
| `networkpolicy.yaml` | The instance pods reach `kube-apiserver` | The CloudNativePG instance manager reports its status there; the object store for WAL and base backups is the platform's `cnpg-backups` policy, see [CloudNativePG → Backups](<https://homelab.wlkr.ch/platform/cloudnative-pg/#backups>) |

### Secrets

| Path | Keys | Written by |
| --- | --- | --- |
| `kv/shot-bridge/accounts` | `lm-username`, `lm-password`, `apns-key-id`, `apns-key-p8` | `make bao-secrets` in the platform repository |
| `kv/shot-bridge/config` | `api-key`, `admin-read-key` (the [admin UI](<https://homelab-apps.wlkr.ch/extractor-admin/index.md>)'s read-only token, which it reads from [a copy](<https://homelab-apps.wlkr.ch/extractor-admin/#copying-the-read-key>)) | The `PushSecret` in `secrets.yaml` |

The accounts path holds values from outside the cluster, so it is its own path: a `bao kv put` replaces a path wholesale. `make bao-secrets` asks for the La Marzocco login, then the APNs key ID and the path to the `.p8` file; Enter leaves the APNs half empty until the key exists.

## Usage

Read the API key and enter it with `https://shot.k8s.wlkr.ch` in the iPhone app's setup screen; **Test** shows the machine's state.

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

- **The image and chart have to be public on GHCR.** The cluster has no pull secret for `ghcr.io/somuch-cloud`, and ArgoCD has no credentials for the chart registry.
- **The sync stops at wave `-1` until `kv/shot-bridge/accounts` exists.** The `ExternalSecret` fails on a missing path, so the Deployment is never created; run `make bao-secrets`.
- **The pod crash-loops while the APNs keys are empty.** The bridge exits on a missing variable rather than starting half-configured.
- **Rotating `kv/shot-bridge/config` changes both keys.** The `PushSecret` writes `IfNotExists`, so rotating is [deleting the path](<https://homelab.wlkr.ch/platform/openbao/#rotating-a-credential>). The phone is logged out: enter the new API key in the app's setup screen, the watch receives it from the phone. The [admin UI](<https://homelab-apps.wlkr.ch/extractor-admin/index.md>) reads a hand copy of `admin-read-key` and answers 403 until it is [copied again](<https://homelab-apps.wlkr.ch/extractor-admin/#copying-the-read-key>).
