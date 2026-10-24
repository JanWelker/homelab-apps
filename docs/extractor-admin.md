---
description: "The Extractor admin UI on the cluster: read-only pages over the shot bridge's diagnostics, behind the Authentik outpost."
---

# Extractor admin UI

Read-only pages over the [shot bridge](shot-bridge.md)'s diagnostics: the shots
recorded with the app's diagnostics switch on, their curves, merged timelines
and stop legs, the uploaded logs, and the calibration runs. It has no login of
its own and reads the bridge server side with the bridge's read-only token,
which never reaches a browser. The source, the image and the chart live in
[somuch-cloud/extractor.cafe](https://github.com/somuch-cloud/extractor.cafe/tree/main/admin);
the chart is published to `ghcr.io/janwelker/charts`, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [extractor-admin.k8s.wlkr.ch](https://extractor-admin.k8s.wlkr.ch) |
| Authentication | The Authentik outpost in front, per [Conventions → Authentication is Authentik's](conventions.md#6-authentication-is-authentiks-not-the-applications) |
| Storage | None; everything is read from the bridge on each request |
| Dials | The bridge's pods in `shot-bridge`, nothing outside the cluster |
| Files | [`extractor-admin/`](https://github.com/JanWelker/homelab-apps/tree/main/extractor-admin) |

## Configuration

| Setting | Why |
| --- | --- |
| Own chart, values in `application.yaml` | The chart ships the Deployment, Service, `HTTPRoute` and `CiliumNetworkPolicy`; this directory adds the namespace and the secret |
| `HTTPRoute` targets `authentik-server` | The admin UI has no login; the chart refuses a route to its own Service. The platform repository's provider forwards to `extractor-admin.extractor-admin.svc` after the login |
| Policy admits the Authentik server pods only | No request can skip the outpost; egress is DNS and the bridge's pods |
| The bridge's `admin.enabled: true` | Passes `BRIDGE_ADMIN_READ_KEY` to the bridge and lets this namespace's pods in on 8080 |

### Secrets

| Path | Keys | Written by |
| --- | --- | --- |
| `kv/shot-bridge/config` | `admin-read-key` | The `PushSecret` in [`shot-bridge/secrets.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/shot-bridge/secrets.yaml) |

The bridge and this UI read the same property, so the token cannot drift
apart. It may only read the debug routes and the logs; every other bridge
route answers 403.

## Health check

```bash
kubectl -n extractor-admin get pods,externalsecret,httproute
kubectl -n extractor-admin logs deploy/extractor-admin    # view GET /shots user=<you> status=200
```

The hostname answers with Authentik's login first, then the shot list.

## Pitfalls

- **The image and chart have to be public on GHCR**, as for the bridge: the
  cluster has no pull secret for `ghcr.io/janwelker`.
- **401 or 403 from the bridge** in the pod's log means the token differs or
  the bridge's `admin.enabled` is off.
- **Only shots recorded with diagnostics on appear.** The token cannot list
  the other shots, by design.
