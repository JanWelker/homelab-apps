---
description: "Jellyfin on the cluster: the household's own media server, plain manifests around the official image, no database of its own and the Authentik proxy outpost in front of its login."
---

# Jellyfin

[Jellyfin](https://jellyfin.org/) serves the household's own films, series and
music. It keeps its library in SQLite beside the files, so it is the one
application here with no `Cluster` behind it. Upstream publishes an image and
no chart, so this is a Deployment, a Service and an `HTTPRoute` around the
official image, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [media.k8s.wlkr.ch](https://media.k8s.wlkr.ch) |
| Authentication | Authentik proxy outpost, in front of Jellyfin's own login. Browsers only — see [Pitfalls](#pitfalls) |
| Storage | Three PVCs: the library, the configuration and database, and the transcode cache |
| Database | None. SQLite on the configuration volume |
| Secrets | None. Jellyfin generates its own and keeps them on the volume |
| Files | [`jellyfin/`](https://github.com/JanWelker/homelab-apps/tree/main/jellyfin) |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests, no chart | Jellyfin publishes no chart; the community ones repackage the same image |
| The namespace enforces `restricted` | The image has no entrypoint that needs root: given `fsGroup` it runs as uid 1000, drops every capability and needs no privilege escalation |
| No CloudNativePG `Cluster` | Jellyfin has no external-database option. Its SQLite lives on the configuration volume, which is why that volume and not a database is what gets restored |
| `JELLYFIN_PublishedServerUrl` | What the server hands clients as its own address. Without it Jellyfin advertises the pod IP and every remote client builds unreachable URLs |
| A separate cache volume | ffmpeg writes transcode segments continuously; keeping them off the configuration volume means a full cache cannot corrupt the library database |
| `/tmp` as an `emptyDir` | So the transcode temporaries never touch the container's root filesystem |
| No CPU limit | A throttled transcode stutters rather than failing, and CPU is the resource Jellyfin actually needs in bursts. Memory is capped, because a runaway there takes the node with it |
| `HTTPRoute` targets `authentik-server`, not the app | Jellyfin has no OIDC support, so the outpost sits in front of its own login and browser users authenticate twice — [Conventions → Authentication is Authentik's](conventions.md#6-authentication-is-authentiks-not-the-applications). The cross-namespace `backendRef` works only because the platform's `referencegrant.yaml` names this namespace; pointing the route at the Jellyfin Service removes the authentication layer, so it deserves a second look in review |

### Storage

| Volume | Holds | Rebuildable |
| --- | --- | --- |
| `jellyfin-media` | The files themselves | No |
| `jellyfin-config` | SQLite, users, API keys, plugins | No — this is what a restore needs |
| `jellyfin-cache` | Transcode segments, images | Yes, at the cost of one re-scan |

All three carry `Prune=false`. The 200Gi on the library is a starting number,
not a measurement: growing a `rook-ceph-block` claim is an edit to the PVC.

### Network policy

Every rule in
[`jellyfin/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/jellyfin/networkpolicy.yaml),
and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

| Rule | Why |
| --- | --- |
| Ingress on 8096 from the Authentik server pods only, with an L7 `http` rule | The outpost is the only path to Jellyfin. No `fromEntities: ingress`, so a request straight from the Gateway cannot skip the login |
| No Prometheus rule | Jellyfin exposes no metrics endpoint and there is no database pod here to scrape |
| Egress to the metadata providers | What a library scan asks for titles, posters and track listings. A scan that finds nothing and reports no error is this list missing a name |
| Egress to `repo.jellyfin.org` and `raw.githubusercontent.com` | The plugin catalogue and the manifests it points at. Without them the plugin page is empty |
| No multicast, no `kube-apiserver` | DLNA and the client auto-discovery broadcast are deliberately not served: the server is found by its hostname or not at all |

## Usage

### Getting media in

There is no share and no upload form; the library volume is `ReadWriteOnce`
and belongs to the pod.

```bash
kubectl -n jellyfin cp <file> deploy/jellyfin:/media/films/
kubectl -n jellyfin exec deploy/jellyfin -- ls /media
```

Then Dashboard → Libraries → Scan. A library added in the UI points at a path
under `/media`.

### First login

Jellyfin runs its setup wizard on the first visit: it creates the first
account and no password is generated anywhere. Do that before handing the
hostname out — the wizard is open to whoever reaches it, and past the outpost
that is anyone Authentik knows.

## Health check

```bash
kubectl -n jellyfin get pods
kubectl -n jellyfin exec deploy/jellyfin -- wget -qO- localhost:8096/health
kubectl -n jellyfin exec deploy/jellyfin -- df -h /cache /media
```

`/health` answers `Healthy` as plain text. The two volumes are worth the same
glance: a full cache shows up as playback that starts and stops, not as an
error.

## Pitfalls

!!! warning "Native apps do not work, on purpose"
    The outpost authenticates with a browser session cookie. The iOS, Android and TV clients speak the API directly and have nowhere to complete an Authentik login, so they get a redirect they cannot follow. Making them work means adding a `skip_path_regex` to the Jellyfin provider in the platform repository — and because almost every Jellyfin API path sits at the root, any regex broad enough to help leaves Jellyfin's own login as the only boundary for those paths. That is a decision to take deliberately, not a default.

- **The first visitor owns the server.** The setup wizard has no password of
  its own; past the outpost it is open.
- **A transcode is CPU, and there is no GPU here.** Direct play works for
  anything the client understands; everything else is software transcoding on
  shared cores. Pre-transcoding the library is cheaper than adding cores.
- **A scan that finds no metadata is usually the egress policy.** Jellyfin
  reports a title with no poster rather than an error. Check the Hubble drop
  log for the provider's hostname.
