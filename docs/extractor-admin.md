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
| `kv/extractor-admin/config` | `admin-read-key` | By hand, as a copy of the bridge's property in `kv/shot-bridge/config`, which the `PushSecret` in [`shot-bridge/secrets.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/shot-bridge/secrets.yaml) generates — see [Copying the read key](#copying-the-read-key) |

A copy, because the `openbao-apps` store confines each namespace to its own
`kv/<namespace>/` ([Conventions → Real secrets come from OpenBao](conventions.md#7-real-secrets-come-from-openbao)).
The token may only read the bridge's debug routes and the logs; every other
bridge route answers 403.

## Usage

### Copying the read key

Once before the first sync, and again whenever `kv/shot-bridge/config` is
rotated. Run from the platform repository's checkout.

1. Log in inside the pod with the root token:

    ```bash
    kubectl -n openbao exec -it openbao-0 -- bao login
    ```

2. Copy the property; it is alphanumeric, so it needs no JSON escaping:

    ```bash
    key="$(kubectl -n openbao exec openbao-0 -- bao kv get -mount=kv -field=admin-read-key shot-bridge/config)"
    printf '{"admin-read-key":"%s"}' "$key" | kubectl -n openbao exec -i openbao-0 -- bao kv put -mount=kv extractor-admin/config -
    unset key
    ```

3. Drop the token the login cached in the pod:

    ```bash
    kubectl -n openbao exec openbao-0 -- sh -c 'rm -f "$HOME/.bao-token"'
    ```

4. After a rotation, push the value through and restart the UI, which reads
   it into an environment variable:

    ```bash
    kubectl -n extractor-admin annotate externalsecret extractor-admin force-sync="$(date +%s)" --overwrite
    kubectl -n extractor-admin rollout restart deploy/extractor-admin
    ```

## Health check

```bash
kubectl -n extractor-admin get pods,externalsecret,httproute
kubectl -n extractor-admin logs deploy/extractor-admin    # view GET /shots user=<you> status=200
```

The hostname answers with Authentik's login first, then the shot list.

## Pitfalls

- **The image and chart have to be public on GHCR**, as for the bridge: the
  cluster has no pull secret for `ghcr.io/janwelker`.
- **401 or 403 from the bridge** in the pod's log means the copy is stale —
  [copy the read key](#copying-the-read-key) again — or the bridge's
  `admin.enabled` is off.
- **Only shots recorded with diagnostics on appear.** The token cannot list
  the other shots, by design.
