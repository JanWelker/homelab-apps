---
description: "OpenCloud on the cluster: plain manifests around the official image, PosixFS on one volume, no database, and Authentik as the identity provider for the web, desktop and mobile clients."
---

# OpenCloud

[OpenCloud](https://opencloud.eu/) is the household's file sync and share:
one Go binary, no database, with desktop, iOS and Android clients. Upstream
publishes no open Helm chart, so this is a Deployment, a Service and a PVC
around the official image, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [cloud.infra.k8s.wlkr.ch](https://cloud.infra.k8s.wlkr.ch), LAN and VPN only |
| Authentication | Authentik OIDC for every client; the built-in identity provider does not run |
| Storage | `rook-ceph-block` PVC for `/var/lib/opencloud`, the PosixFS driver |
| Database | None; metadata lives in extended attributes and the embedded NATS store |
| Secrets | `kv/opencloud/config` in OpenBao, generated once |
| Files | [`opencloud/`](https://github.com/JanWelker/homelab-apps/tree/main/opencloud) |

## Storage

PosixFS keeps the files on the volume in the tree the user sees, with the
metadata in xattrs, which ext4 provides, and versions, trash and the search
index beside them. One volume holds the whole instance, so the nightly
[Velero snapshot](https://homelab.wlkr.ch/operations/backups/) is a complete
copy, and a restore is readable with `ls`. The driver's non-collaborative
mode requires that nothing else writes to the tree, which a single
Deployment on a `ReadWriteOnce` volume guarantees.

The alternative, blobs in an S3 bucket with metadata on a volume, splits
one instance across two backup mechanisms, one of which does not exist for
buckets here, and upstream documents no migration into or out of it.

Upstream's backup guidance is to stop the instance first. The RBD snapshot
is crash-consistent instead: metadata is written per operation on the same
filesystem, and the run at 02:00 sees no sync traffic. The search index
is rebuilt if it disagrees after a restore; nothing is lost.

## Configuration

The values in `opencloud/deployment.yaml` that are not self-explanatory:

| Setting | Why |
| --- | --- |
| `opencloudeu/opencloud-rolling`, not the production `opencloudeu/opencloud` | Rolling ships every three weeks on a current Alpine; the production line gets a release about every six months, and its image carried a fixable critical in an Alpine package that the [image-scan gate](conventions.md#2-official-upstream-sources-only) refuses. Move to the production line at a release that passes the gate. Either way a major bump waits for a human |
| `args: ["server"]`, no `init` | `opencloud init` only writes random secrets and IDs into `opencloud.yaml`. Every one of them arrives as an environment variable from `opencloud-env` instead, so `/etc/opencloud` is an emptyDir and the pod carries nothing a backup would have to protect |
| `strategy: Recreate`, one replica | The volume is `ReadWriteOnce`, and PosixFS in non-collaborative mode tolerates one writer |
| `runAsUser: 1000`, `fsGroup: 1000`, read-only root, the namespace enforces `restricted` | The image runs as that user and writes only under `/var/lib/opencloud`, `/etc/opencloud` and `/tmp`, the last two emptyDirs |
| `OC_EXCLUDE_RUN_SERVICES=idp` | Authentik is the identity provider; the built-in one would be a second login |
| `OC_OIDC_ISSUER=https://auth.k8s.wlkr.ch/` | The four Authentik providers run in global issuer mode, whose issuer is the bare hostname; see [OIDC](#oidc) |
| `PROXY_CSP_CONFIG_FILE_LOCATION`, the policy in `opencloud/csp.yaml` | The default Content-Security-Policy allows connections and frames to the server itself only, so the browser refuses the discovery, token and silent-renew requests to an external IdP and the page spins forever. The file adds `auth.k8s.wlkr.ch` to `connect-src` and `frame-src`; OpenCloud merges it into the default rather than replacing it, so the default's `update.opencloud.eu` and GitHub app-store hosts stay in the browser policy. They matter only to a browser, the update check is off, and the server itself reaches neither |
| `PROXY_OIDC_REWRITE_WELLKNOWN` | The desktop and mobile clients discover the identity provider through the server's own `/.well-known/openid-configuration` |
| `PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD=jwt` | Authentik's access tokens are JWTs, so the server checks signature and issuer itself instead of calling userinfo on every request |
| `PROXY_OIDC_AUDIENCES`, the four client IDs | Authentik writes the client ID into `aud`, so the server accepts only tokens minted for one of its own clients, not any token from the same issuer. Without the list the proxy logs at every start that audience validation is off |
| `PROXY_AUTOPROVISION_ACCOUNTS`, with `sub` as the username | Accounts are created in the built-in IDM on first login and keyed on the `sub` claim, which never changes, per [Conventions → Authentication](conventions.md#6-authentication-is-authentiks-not-the-applications). Upstream's own autoprovisioning example does the same. Users see display names, never this value |
| `GRAPH_USERNAME_MATCH=none` | Authentik's `sub` is a SHA-256 hex string, and the default rule refuses a username that starts with a digit: `Invalid username`, and the first login ends in a 400 |
| `FRONTEND_READONLY_USER_ATTRIBUTES` | Name and mail come from Authentik on every login, so the profile page must not offer to edit them |
| `PROXY_ROLE_ASSIGNMENT_DRIVER=oidc` on the `groups` claim, `GRAPH_ASSIGN_DEFAULT_USER_ROLE=false` | The role comes from Authentik group membership, and a user in neither group gets no role and no access; see [Usage](#usage) |
| `STORAGE_USERS_ID_CACHE_STORE=nats-js-kv` | PosixFS requires the NATS key-value store for its id cache; the embedded NATS provides it |
| `FRONTEND_CHECK_FOR_UPDATES=false` | The web frontend's version check is the one outbound call the server makes on its own. Nothing phones home, the same rule as every platform component |
| `PROXY_DEBUG_ADDR=0.0.0.0:9205` | Every service in the binary has a debug port; the proxy's carries the request metrics, the health endpoints and the one `ServiceMonitor` |
| `HTTPRoute` on `infra-gateway`, not `apps-gateway` | Only `apps-gateway` gets a public DNS record. Phones sync on the LAN and the VPN; moving to the public gateway is one route change |

### OIDC

OpenCloud's web, desktop, iOS and Android clients are four OIDC clients with
IDs fixed by the clients (`web`, `OpenCloudDesktop`, `OpenCloudIOS`,
`OpenCloudAndroid`), all public, authorization code with PKCE, so
`opencloud/authentik-blueprint.yaml` holds four providers and four
applications. Only the web one is visible in the Authentik library; the
native ones carry `blank://blank` as their launch URL.

The server and the native clients verify every token against the one
issuer the server advertises, and Authentik derives a provider's issuer from
its application slug. All four providers therefore use `issuer_mode:
global`, and the platform rewrites `/.well-known/openid-configuration` on
`auth.k8s.wlkr.ch` to the `opencloud` application's document; see
[One issuer for OpenCloud](https://homelab.wlkr.ch/platform/authentik/#one-issuer-for-opencloud).

The desktop client redirects to a loopback address with a random port, so
its redirect URI is a regular expression; the mobile ones are custom-scheme
URLs the apps register. There are no client secrets, so nothing lands in
OpenBao for Authentik's side, and the platform repository only mounts the
blueprint.

### Secrets

`secrets.yaml` generates what `opencloud init` would: a `Password`
generator for the JWT, transfer, URL-signing and service-account secrets,
the machine-auth and system-user API keys and the IDM service passwords,
which the `users`, `groups`, `auth-basic` and `graph` services also receive
as their LDAP bind passwords, and one `UUID` generator per ID, because a `UUID` generator yields one
value and a `PushSecret` reads one generator. Each `PushSecret` writes its
keys into `kv/opencloud/config` once; the `ExternalSecret` templates them
into `opencloud-env` under the environment variable names. Losing the
OpenBao path and regenerating is a new instance: the JWT secret signs the
internal tokens and the IDs name the storage mount and the system user, so
the data on the volume would no longer match.

### Network policy

Every rule in `opencloud/networkpolicy.yaml`, and why it is there. The
shape is [Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy).

| Rule | Why |
| --- | --- |
| Ingress from `ingress` on 9200 | The Gateway reaches the server directly; OpenCloud handles its own login, and the desktop and mobile clients arrive the same way |
| Ingress from Prometheus on 9205, `GET /metrics` only | The proxy's metrics; the health endpoints on the same port are the kubelet's, covered by `host` and `remote-node` |
| Egress from the server to the Authentik server pods on 9000 | Discovery, the signing keys and the token endpoint go to `auth.k8s.wlkr.ch`, which resolves to the public address and is `world` to Cilium. The Gateway's Envoy then checks this policy against the Authentik pod it picks and answers 403 itself when that pod is not listed, so both the name and the pod are allowed |
| Egress from the server to `auth.k8s.wlkr.ch` on 443 | The other half of the same path. Hubble records one dropped SYN to this name at each pod start: the first packet after a fresh DNS answer races the FQDN policy update and the retransmit passes, the [known artefact](https://homelab.wlkr.ch/platform/security-policies/#network-policies), not a missing rule |

That is the complete list. No app store, no update check, no mail, no
object store: the search index and NATS run inside the process.

## Usage

Membership in one of two Authentik groups is an account:

| Group | OpenCloud role |
| --- | --- |
| `opencloudAdmin` | Administrator |
| `opencloudUser` | User |

A user in neither group can log in to Authentik but is refused by OpenCloud
with no role assigned. The groups also appear as groups inside OpenCloud,
because autoprovisioning mirrors the `groups` claim.

Clients: the [desktop client](https://github.com/opencloud-eu/desktop/releases)
for macOS 13 and later, Windows and Linux, the iOS app from the App Store and
the Android app from Google Play or F-Droid. Each takes the server URL and
opens Authentik in the browser.

## Health check

```bash
kubectl -n opencloud get pods,pvc,externalsecret,pushsecret
curl -s https://cloud.infra.k8s.wlkr.ch/.well-known/openid-configuration | jq -r .issuer
```

The pod is `Running`, every `PushSecret` and the `ExternalSecret` are
`Ready`, and the issuer printed is `https://auth.k8s.wlkr.ch/`. After a
first start, the `idm.boltdb` on the volume is larger than the 32 KiB of an
empty Bolt file; see [Pitfalls](#pitfalls).

## Pitfalls

| Symptom | Cause |
| --- | --- |
| `ExternalSecret` stays `SecretSyncedError` on the first sync | The `PushSecret`s and the `ExternalSecret` are in different waves but OpenBao is written asynchronously; the retry covers it within minutes |
| The web page shows the loading animation forever, the console reports a Content-Security-Policy violation for `auth.k8s.wlkr.ch` | The served policy is the default, not `csp.yaml`: the ConfigMap or `PROXY_CSP_CONFIG_FILE_LOCATION` is missing, or the mount path differs from the variable |
| Login succeeds in Authentik, OpenCloud answers 403 | The user is in neither group, or the issuer in the token differs from `OC_OIDC_ISSUER`: a provider without `issuer_mode: global` |
| The desktop client's login tab never returns | The loopback redirect did not match the regular expression; the port is random and the path may be empty |
| Prometheus shows the target down | The policy allows `GET /metrics` only; any other path on 9205 from Prometheus is refused |
| Login ends on "Not logged in"; the log shows `failed to add user` with `LDAP Result Code 49` from `graph` and `not found` from `idm` | The IDM database under `idm/` on the volume is a bare Bolt file: a first pod that died during the bootstrap, as in the row below, left it created but without the service users, and every later start sees the file and skips the bootstrap. Remove the `idm` directory the same way as `search` below and restart; the next start bootstraps it. Only safe while no account exists yet, which is the case when this symptom appears |
| The pod exits with `error parsing mapping JSON: unexpected end of JSON input` from the `search` service | The Bleve index under `search/` on the volume was created by a pod that died before writing the mapping, which happens when another service fails on the same first start. Remove the `search` directory from the volume, from a pod on the same node that mounts the PVC while the container is in its back-off, and the index is rebuilt from the files on the next start. Scaling the Deployment to zero first does not hold: self-heal restores the replica within a minute |
