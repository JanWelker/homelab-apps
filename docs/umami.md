---
description: "Umami on the cluster: cookieless web analytics for every site, plain manifests around the official image, the dashboard behind the Authentik outpost and the tracker paths open."
---

# Umami

[Umami](https://umami.is/) counts the visits to every site: the two
documentation sites, the GitHub Pages projects, Nextcloud and Home Assistant.
It sets no cookie and stores no address, so the sites need no consent banner.
Upstream publishes an image and no chart, so this is a Deployment, a Service
and an HTTPRoute around the official image, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [analytics.k8s.wlkr.ch](https://analytics.k8s.wlkr.ch) |
| Authentication | Authentik proxy outpost, in front of Umami's own login; `/script.js` and `/api/send` pass through |
| Storage | None outside the database |
| Database | CloudNativePG `Cluster` `umami-db` |
| Secrets | `kv/umami/config` in OpenBao |
| Files | [`umami/`](https://github.com/JanWelker/homelab-apps/tree/main/umami) |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests, no chart | One stateless process with one port and one database; the community charts are repackagers |
| The namespace enforces `restricted` | The image runs as uid 1001, needs no capability, and writes only Next.js' cache, which is an `emptyDir` next to `/tmp` |
| `automountServiceAccountToken: false` | Umami never talks to the API server |
| `DATABASE_URL` from `umami-db-app`, key `uri` | Umami wants one connection string, and CloudNativePG assembles it; see [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract) |
| `APP_SECRET` and `TWO_FACTOR_ENCRYPTION_KEY` from OpenBao | The first signs every dashboard session and the second encrypts TOTP secrets; both must survive a rebuild, so neither is generated in the cluster. See [Secrets](#secrets) |
| `DISABLE_UPDATES`, `DISABLE_TELEMETRY`, `PRIVATE_MODE` | No phone-home: no version check, no usage report, no favicon fetch for each tracked site. The egress policy allows nothing outside the cluster, so these are what keep the log free of drops |
| Probes on `/api/heartbeat`, a long `startupProbe` | The first start runs the Prisma migrations before the server answers |
| `revisionHistoryLimit: 2` | Superseded ReplicaSets keep their Trivy config-audit reports until garbage collection; the default keeps ten |
| `HTTPRoute` targets `authentik-server`, not the app | The outpost authenticates and forwards to `umami.umami.svc:3000`. The provider's `skip_path_regex`, in the platform repository, exempts exactly `/script.js` and `/api/send`: the tracker every visitor loads and the endpoint it posts to. Everything else, the dashboard and the rest of the API, is behind the login. The cross-namespace `backendRef` works only because the platform's `referencegrant.yaml` names this namespace; pointing the route at the Umami Service removes the authentication layer, so it deserves a second look in review |
| No `CLIENT_IP_HEADER` | The Gateway's Envoy appends the visitor to `X-Forwarded-For` and the outpost passes it on; Umami reads that header by default. Only the country is stored, from the bundled GeoLite database, never the address |

### Network policy

Every rule in `umami/networkpolicy.yaml`, and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

| Rule | Why |
| --- | --- |
| Ingress on 3000 from the Authentik server pods only | The outpost proxies the tracker paths as well as the dashboard, so the Gateway never talks to the pod. No `fromEntities: ingress`, so a request straight from the Gateway cannot skip the login |
| Ingress from Prometheus on 9187, `GET /metrics` only | The database's metrics. Umami itself exposes none |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |
| Egress to the namespace only | The database. With the three phone-home switches off, nothing else is dialled |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

## Usage

### First login

Umami creates `admin` with the password `umami` on its first start. Change it
under Profile before adding a website; it is the only account, and the only
credential Umami keeps that OpenBao does not.

### Adding a site

1. Settings → Websites → Add website: a name and the hostname. The website
   ID it shows is not a secret; it goes into Git with the snippet.
2. Put the snippet in the site's `<head>`, with `data-domains` set to the
   hostname it should report from:

    ```html
    <script defer src="https://analytics.k8s.wlkr.ch/script.js"
      data-website-id="<id>" data-domains="<hostname>"></script>
    ```

`data-domains` is what keeps a local `zensical serve` or `npm run dev` out of
the numbers: the tracker checks the page's hostname before it sends anything.
A PR preview under the production hostname is not excluded and counts as a
page there.

Where the snippet lives per site:

| Site | Where |
| --- | --- |
| This site and the [platform documentation](https://homelab.wlkr.ch/) | `overrides/partials/integrations/analytics/custom.html`, wired by `[project.extra.analytics] provider = "custom"` in `zensical.toml` |
| A SvelteKit or Vite site on GitHub Pages | `src/app.html` or `index.html` |
| [Home Assistant](home-assistant.md) | `frontend.extra_module_url` in `configuration.yaml`, pointing at a module in the ConfigMap that appends the `<script>` tag; a module is loaded through `import()`, which is not how the tracker expects to be run |

### Secrets

`kv/umami/config` holds two values, 64 hex characters each as Umami documents
them, written once by the `PushSecret` in `secrets.yaml` and never
overwritten — see [Generated secrets](https://homelab.wlkr.ch/platform/openbao/#generated-secrets).

| Key | Read as |
| --- | --- |
| `app-secret` | `APP_SECRET`: signs the dashboard sessions |
| `two-factor-encryption-key` | `TWO_FACTOR_ENCRYPTION_KEY`: encrypts TOTP secrets at rest |

The `ExternalSecret` sits at sync wave `-1`, with the database and ahead of
the Deployment that reads it, and keeps its Secret when deleted
(`deletionPolicy: Retain`). The database password is not here; CloudNativePG
generates it and nothing outside the cluster needs it.

## Health check

```bash
kubectl -n umami get pods
kubectl -n umami get cluster umami-db
curl -sI https://analytics.k8s.wlkr.ch/script.js | head -1
```

The database should report `Cluster in healthy state` and the script should
answer `200` without a redirect to `auth.k8s.wlkr.ch`. The dashboard's
Realtime view is the end-to-end check: open one of the sites and the visit
appears within seconds.

## Pitfalls

!!! warning "Two logins, and the tracker paths behind neither"
    Umami has a login of its own and no OIDC support, so, like Home Assistant, the outpost sits in front of it and browser users authenticate twice. `/script.js` and `/api/send` are exempt on the provider, which is what lets a visitor's browser post a page view; the collect endpoint accepts nothing but page views and events for a known website ID.

- **A visit shows the cluster's country, or none.** Umami takes the visitor
  from `X-Forwarded-For`. If every visit resolves to the same place, the
  header is not reaching the pod: see
  [Behind the Gateway](conventions.md#behind-the-gateway).
- **Deleting `kv/umami/config` logs everyone out.** The `PushSecret` writes
  both keys anew: a rotated `APP_SECRET` invalidates every session and a
  rotated 2FA key every second factor.
- **`data-domains` is the only guard against noise.** A snippet without it
  reports from every copy of the site: a laptop, a preview, a fork.
