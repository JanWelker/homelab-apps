---
description: "Open WebUI on the cluster: one chat front end for the model APIs the household pays for, the upstream chart, CloudNativePG behind it and Authentik as the only way in."
---

# Open WebUI

[Open WebUI](https://openwebui.com/) is the chat front end for the model APIs
the household already pays for. No model runs on the cluster: every answer
comes from a remote API, and what is kept here is the conversation history,
the uploaded documents and the retrieval index. Upstream publishes its own
chart, so this is that chart with values, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [chat.k8s.wlkr.ch](https://chat.k8s.wlkr.ch) |
| Authentication | Authentik OIDC; the local login form is off and there is no local account |
| Storage | A PVC for uploads and the retrieval index |
| Database | CloudNativePG `Cluster` `open-webui-db` |
| Secrets | `kv/open-webui/config` and `kv/open-webui/openai` in OpenBao |
| Files | [`open-webui/`](https://github.com/JanWelker/homelab-apps/tree/main/open-webui) |

## Configuration

| Setting | Why |
| --- | --- |
| The upstream chart, `helm.openwebui.com` | Open WebUI publishes and versions its own chart; the image tag comes with the chart version, so there is one pin |
| `ollama`, `pipelines` and `tika` disabled | Each is a sub-chart with its own workload. Nothing here runs inference and nothing extracts documents locally, so all three would be idle pods |
| `websocket.manager: ""`, the chart's Redis off | One replica needs no shared socket state, and the in-memory manager is what upstream recommends below two. A Redis for one process is a second thing to back up |
| `workload.kind: Deployment` with `Recreate` | The volume is `ReadWriteOnce`; the default rolling replacement would start a second pod that can never attach the disk |
| `DATABASE_URL` from `open-webui-db-app`, key `uri` | One connection string, assembled by CloudNativePG; see [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract). The bundled SQLite would put the history on the same volume as the uploads |
| `WEBUI_SECRET_KEY` from OpenBao | It signs every session cookie. Left to the app it is generated into the data volume, so restoring that volume elsewhere would log everyone out. See [Secrets](#secrets) |
| `persistence.existingClaim` | [`pvc.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/open-webui/pvc.yaml), so the volume carries `Prune=false` like every other one here |
| The chart's `openaiApiKeyExistingSecret`, not an `extraEnvVars` entry | The chart renders an `OPENAI_API_KEY` of its own; a second one of the same name in `extraEnvVars` would shadow it rather than replace it, which reads as a bug the first time someone greps the pod spec |
| `ENABLE_LOGIN_FORM: false`, `ENABLE_SIGNUP: false`, `ENABLE_OAUTH_SIGNUP: true` | Authentik is the only way in, and an account appears the first time someone Authentik already knows signs in. There is no break-glass local account: the first user to sign in becomes the administrator |
| `ENABLE_VERSION_UPDATE_CHECK`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY` | No phone-home. The egress policy allows nothing but the model APIs, so without these the drop log fills with version checks |
| `HTTPRoute` from the chart, pointed at the app | Open WebUI speaks OIDC, so the Gateway reaches it directly and the outpost is not in the path — [Conventions → Authentication is Authentik's](conventions.md#6-authentication-is-authentiks-not-the-applications) |

### OIDC

The provider's blueprint is
[`authentik-blueprint.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/open-webui/authentik-blueprint.yaml),
a ConfigMap targeted at the `authentik` namespace. The client credentials live
in `kv/open-webui/config` and are read from there twice: by Open WebUI, and by
Authentik through its own `ExternalSecret` in the platform repository. Neither
side ever copies the other's value out of a UI.

The redirect URI is `/oauth/oidc/callback` under the one hostname
`auth.k8s.wlkr.ch` — a client that mixes Authentik's names fails every login,
see [One hostname](https://homelab.wlkr.ch/platform/authentik/#one-hostname).

Group management is on: Authentik's `groups` claim decides Open WebUI's groups,
so who may use which model is a membership in Authentik rather than a setting
here.

### Network policy

Every rule in
[`open-webui/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/open-webui/networkpolicy.yaml),
and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

| Rule | Why |
| --- | --- |
| Ingress on 8080 from `ingress` | The Gateway reaches the pod directly; the login is OIDC, so there is no outpost to route around |
| Ingress from Prometheus on 9187, `GET /metrics` only | The database's metrics. Open WebUI exposes none over HTTP |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |
| Egress to the Authentik server pods and `auth.k8s.wlkr.ch` | Discovery and the token exchange |
| Egress to the model APIs | Every prompt leaves through one of these names. Adding a provider in Settings → Connections is only half the change: the name has to be here too, which is the point |
| Egress to Hugging Face | The first document upload downloads the embedding model; nothing else reaches it afterwards |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

## Usage

### Adding a model provider

Anything that speaks the OpenAI API works, including Anthropic's compatibility
endpoint and OpenRouter. Two steps, in this order:

1. Add the hostname to the `open-webui` egress policy and merge it. Without
   it the connection test fails with a timeout that looks like a wrong key.
2. Settings → Connections → add the base URL and the key.

The key that is in Git's reach — the one in `kv/open-webui/openai` — is only
the default OpenAI one. Keys added through the UI are stored in the database.

### Secrets

Two paths. `kv/open-webui/config` is generated: written once by the
`PushSecret` in `secrets.yaml` and never overwritten — see [Generated secrets](https://homelab.wlkr.ch/platform/openbao/#generated-secrets).
`kv/open-webui/openai` is typed in with `make bao-secrets` in the platform
repository, its own path because a `bao kv put` replaces a path wholesale and
would take the generated keys with it.

| Path | Key | Read as |
| --- | --- | --- |
| `kv/open-webui/config` | `webui-secret-key` | `WEBUI_SECRET_KEY`: signs the session cookies |
| `kv/open-webui/config` | `oidc-client-id` | `OAUTH_CLIENT_ID`, and the same value on Authentik's side |
| `kv/open-webui/config` | `oidc-client-secret` | `OAUTH_CLIENT_SECRET`, likewise |
| `kv/open-webui/openai` | `api-key` | `OPENAI_API_KEY`: the default provider's key |

## Health check

```bash
kubectl -n open-webui get pods
kubectl -n open-webui get cluster open-webui-db
curl -sI https://chat.k8s.wlkr.ch/health | head -1
```

The database should report `Cluster in healthy state`. `/health` answers `200`
without a session, so a redirect to `auth.k8s.wlkr.ch` there means the route
is pointing at the outpost rather than the app.

## Pitfalls

!!! warning "The first person to sign in is the administrator"
    There is no local admin and no break-glass account: `ENABLE_LOGIN_FORM` is off. Whoever completes the first Authentik login owns the instance, and everyone after them arrives as a pending user that administrator has to approve. Sign in yourself before telling anyone the hostname.

- **A new provider fails as a timeout, not as a refusal.** The egress policy
  allows a fixed list of names; a base URL that is not on it hangs until the
  connection test gives up. Check the Hubble drop log before the key.
- **The retrieval index lives on the volume, the history in Postgres.**
  Restoring one without the other leaves documents that cannot be searched, or
  searches that point at documents that are gone.
- **A model API outage looks like a broken login.** The chat page renders
  before the model list loads; if the list is empty and the drop log is quiet,
  it is the provider, not Authentik.
