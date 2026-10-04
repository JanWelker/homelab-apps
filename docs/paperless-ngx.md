---
description: "Paperless-ngx on the cluster: the household's paper scanned, OCR'd and searchable, plain manifests around the official image, CloudNativePG behind it and Authentik as the normal login."
---

# Paperless-ngx

[Paperless-ngx](https://docs.paperless-ngx.com/) is where the household's
paper goes: scanned, OCR'd, tagged and searchable, with the original PDF kept
untouched beside the text. Upstream publishes an image and no chart — the
charts that exist are repackagers — so this is a Deployment, a broker, a
Service and an `HTTPRoute` around the official image, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [paperless.k8s.wlkr.ch](https://paperless.k8s.wlkr.ch) |
| Authentication | Authentik OIDC, with one local `admin` kept as break-glass |
| Storage | Two PVCs: the originals and the archive, and the index and the consume folder |
| Database | CloudNativePG `Cluster` `paperless-ngx-db` |
| Broker | Redis, the official image, on its own small volume |
| Secrets | `kv/paperless-ngx/config` in OpenBao |
| Files | [`paperless-ngx/`](https://github.com/JanWelker/homelab-apps/tree/main/paperless-ngx) |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests, no chart | Paperless publishes no chart; the community ones repackage the same image with their own values |
| The namespace enforces `baseline` | The image's entrypoint starts as root to take ownership of the volumes and drops to uid 1000 itself, which `restricted` forbids. `audit` and `warn` stay at `restricted`, so a change that no longer needs root is visible |
| A Redis of its own | Paperless runs its consumption and its scheduled tasks through Celery, and there is no setting that removes the broker. It gets a small volume of its own, because a restart that loses the queue loses whatever was mid-consumption |
| Database from `paperless-ngx-db-app` | Paperless wants the five fields rather than one URL, and CloudNativePG writes all five; see [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract) |
| `PAPERLESS_SECRET_KEY` from OpenBao | It signs the sessions; generated into the container it would change on every rebuild. See [Secrets](#secrets) |
| The consume and export folders inside the data volume | Upstream's one hard rule about the consume folder is that it must not be inside the media folder, or a consumed file lands in the archive twice |
| `PAPERLESS_OCR_LANGUAGE: deu+eng`, `PAPERLESS_OCR_LANGUAGES` wider | Most of the paper is German with English on top; the second variable installs the extra tesseract packages so a French or Italian document can be re-OCR'd without a new image |
| `PAPERLESS_USE_X_FORWARD_*` and `PAPERLESS_PROXY_SSL_HEADER` | Traffic arrives from Envoy inside the pod CIDR and TLS ends at the Gateway; without these Paperless builds `http://` links on an `https://` site. See [Behind the Gateway](conventions.md#behind-the-gateway) |
| No Gotenberg and no Tika | Those two exist to convert Office documents; what gets scanned here is PDFs and images, and each is another workload to keep patched. Adding them later is two Deployments and two variables |
| `PAPERLESS_ENABLE_UPDATE_CHECK: false` | No phone-home. The egress policy allows nothing but Authentik, so without it the drop log fills with version checks |
| `HTTPRoute` targets the app, not `authentik-server` | Paperless speaks OIDC, so the outpost is not in the path — [Conventions → Authentication is Authentik's](conventions.md#6-authentication-is-authentiks-not-the-applications) |

### OIDC

django-allauth, which Paperless uses, reads its whole provider configuration
from one JSON document in `PAPERLESS_SOCIALACCOUNT_PROVIDERS` — client secret
included. That document is assembled by the `ExternalSecret` template in
[`secrets.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/paperless-ngx/secrets.yaml)
from the two values in OpenBao, so the secret never passes through Git.

`PAPERLESS_DISABLE_REGULAR_LOGIN` and `PAPERLESS_REDIRECT_LOGIN_TO_SSO` turn
the login page into a redirect to Authentik. Neither disables the Django admin
at `/admin/`, which is exactly what makes `admin` usable as break-glass.

The provider's blueprint is
[`authentik-blueprint.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/paperless-ngx/authentik-blueprint.yaml);
the redirect URI is allauth's `/accounts/oidc/authentik/login/callback/` under
the one hostname `auth.k8s.wlkr.ch`, see
[One hostname](https://homelab.wlkr.ch/platform/authentik/#one-hostname).

### Network policy

Every rule in
[`paperless-ngx/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/paperless-ngx/networkpolicy.yaml),
and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

| Rule | Why |
| --- | --- |
| Ingress on 8000 from `ingress` | The Gateway reaches the app directly; the login is OIDC, so there is no outpost to route around |
| Ingress from Prometheus on 9187, `GET /metrics` only | The database's metrics. Paperless exposes none |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |
| Egress to the namespace | The database and the broker |
| Egress to the Authentik server pods and `auth.k8s.wlkr.ch` | Discovery and the token exchange. It is the only name outside the cluster that the app may dial, which is the point: OCR is local and no document ever leaves |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

## Usage

### Getting a document in

| Way | How |
| --- | --- |
| The web UI | Drag onto the dashboard; it lands in the consume folder and is picked up within seconds |
| The consume folder | `kubectl -n paperless-ngx cp <file> deploy/paperless-ngx:/usr/src/paperless/data/consume/` |
| A scanner | Anything that can write to the folder above; the mobile apps speak the API with a token from Settings → My Profile |

### Secrets

`kv/paperless-ngx/config` holds four values, written once by the `PushSecret`
in `secrets.yaml` and never overwritten — see [Generated secrets](https://homelab.wlkr.ch/platform/openbao/#generated-secrets).

| Key | Read as |
| --- | --- |
| `secret-key` | `PAPERLESS_SECRET_KEY`: signs the sessions |
| `admin-password` | The break-glass `admin` account, read only when Paperless first starts |
| `oidc-client-id` | Part of the assembled provider JSON, and the same value on Authentik's side |
| `oidc-client-secret` | Likewise |

## Health check

```bash
kubectl -n paperless-ngx get pods
kubectl -n paperless-ngx get cluster paperless-ngx-db
kubectl -n paperless-ngx logs deploy/paperless-ngx -c paperless-ngx --tail=20
curl -sI https://paperless.k8s.wlkr.ch/accounts/login/ | head -1
```

The database should report `Cluster in healthy state`. A document that sits in
the consume folder and never appears is the broker: check that the Redis pod
is Running before anything else.

## Pitfalls

!!! warning "An SSO user arrives with no permissions"
    `PAPERLESS_SOCIAL_AUTO_SIGNUP` creates the account on first login, but it is an ordinary user who can see nothing. Grant it what it needs as `admin` through `/admin/`, or the person sees an empty, apparently broken Paperless.

- **The break-glass login is `/admin/`, not the front page.** The normal login
  redirects to Authentik; `admin` signs in at
  `https://paperless.k8s.wlkr.ch/admin/` with the password from OpenBao.
- **Deleting `kv/paperless-ngx/config` does not change the admin password.**
  It is read only when Paperless first creates the account. The new value gets
  written down and the old one still logs you in — reset it in `/admin/`.
- **The index is rebuildable, the originals are not.** Both volumes carry
  `Prune=false`, but only the media one is irreplaceable; `document_index
  reindex` rebuilds the other from it.
