# Wollbi Adventsfenster

[advent.wollbi.ch](<https://advent.wollbi.ch>) is the invitation to the street's advent windows: the flyer, the dates and the calendar file to import. It was a Pelican site until the pages became rows in a database: the content is now edited at `/admin` and the repository holds the application, not the text. The image is built in [JanWelker/advent.wollbi.ch](<https://github.com/JanWelker/advent.wollbi.ch>), so its upstream is our own — per [Conventions → Official upstream sources only](<https://homelab-apps.wlkr.ch/conventions/#2-official-upstream-sources-only>).

## At a glance

|  |  |
| --- | --- |
| URL | [advent.wollbi.ch](<https://advent.wollbi.ch>) — public, no login |
| Authentication | Payload signs editors in through Authentik over OIDC, members of `wollbi-editors` only; no local accounts; `/seed` redirects to `/` |
| Storage | A PVC for what editors upload after the seed |
| Database | CloudNativePG `Cluster` `advent-wollbi-db` |
| Secrets | `kv/advent-wollbi/config`, `kv/advent-wollbi/seed` and `kv/advent-wollbi/oidc` in OpenBao |
| Files | [`advent-wollbi/`](<https://github.com/JanWelker/homelab-apps/tree/main/advent-wollbi>) |
| Source | [JanWelker/advent.wollbi.ch](<https://github.com/JanWelker/advent.wollbi.ch>) |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests around our own image | One Next.js process with one port and one database; the site repository's README is the whole deployment contract |
| The namespace enforces `restricted` | The image is distroless and runs as uid 65532, its `nonroot` user, with a read-only root filesystem; the two things it writes, the uploads and Next.js' render cache, are volumes. There is no shell in it, so `kubectl exec` is for `node -e`, not for poking around |
| `DATABASE_URL` from `advent-wollbi-db-app`, key `uri` | Payload wants one connection string and CloudNativePG assembles it; see [the contract](<https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract>) |
| `PAYLOAD_SECRET` from OpenBao | It signs every editor session. The `PushSecret` in `secrets.yaml` writes it once, `IfNotExists`, so a rebuilt cluster reads the same value back and nobody is logged out; see [Conventions → Real secrets come from OpenBao](<https://homelab-apps.wlkr.ch/conventions/#7-real-secrets-come-from-openbao>) |
| `NEXT_PUBLIC_SERVER_URL` | The origin Payload trusts for CSRF and builds absolute URLs from. TLS ends at the Gateway, so the pod's own address is the wrong answer — see [Behind the Gateway](<https://homelab-apps.wlkr.ch/conventions/#behind-the-gateway>) |
| An `emptyDir` on `/app/.next/cache` | Next.js writes its render cache at runtime and the root filesystem is read-only. It is a cache: losing it on a restart costs one slow first request |
| Two rules on one `HTTPRoute` | Every path reaches the app, `/admin` and `/api` included: Payload checks the editor's session itself, so the Gateway has nothing to gate. `/seed` redirects to `/`: the seed hook calls the Service, so nothing outside the namespace has a reason to reach it, and Gateway API has no rule that refuses a request |
| The media collection accepts PDFs and `text/calendar` | The flyer and the `.ics` are content here, not attachments; as uploads the CMS knows about them, where the Pelican site had them as links in prose that outlive the file |
| `/healthz` answers without the database | A database outage should show as an empty page, not as a pod the kubelet restarts in a loop |

### Seeding

The Pelican content is imported once, by a `PostSync` hook that `curl`s a route inside the image. The route is part of the build, so there is no second image to keep in step; it refuses without the secret the pod already holds, and does nothing once a page exists. That is what makes it safe to run after every sync rather than once by hand.

What it does, in order, and only on an empty database:

1. Imports every file in the site repository's `public/seed/images/` as media — ten of them, including the flyers of 2023 and 2024 and the 2024 calendar, which the current site no longer links but which are the record of those years.
2. Writes the two pages: Willkommen and Info.

Afterwards the database is the source of truth and the seed is a no-op. The Job's `activeDeadlineSeconds` is the backstop: a site that never answers fails the sync instead of holding the Application in Syncing, and the curl's own retries fit inside it.

### OIDC

The provider, the `wollbi-editors` group and the binding are in [`advent-wollbi/authentik-blueprint.yaml`](<https://github.com/JanWelker/homelab-apps/blob/main/advent-wollbi/authentik-blueprint.yaml>); the platform mounts it, and reads the client secret, as in [Authentik → Adding an application](<https://homelab.wlkr.ch/platform/authentik/#adding-an-application>).

| Setting | Why |
| --- | --- |
| A confidential client, `client_id` `advent-wollbi` in clear | Payload exchanges the code on the server, where a secret can live; the ID is not a secret |
| The `payload-oauth2` plugin, local strategy off | Payload has no built-in OIDC; with the local strategy off there are no passwords to leak or reset |
| The group checked twice | Authentik's binding refuses everyone else; the app also refuses a `groups` claim without `wollbi-editors`, so an unbound application does not open the site to every Authentik account |
| Users matched by email | An editor created before the switch keeps their pages when they first sign in with the same email |

The rules in [`advent-wollbi/networkpolicy.yaml`](<https://github.com/JanWelker/homelab-apps/blob/main/advent-wollbi/networkpolicy.yaml>), and why each is there. The shape is [Conventions → Ship a `CiliumNetworkPolicy`](<https://homelab-apps.wlkr.ch/conventions/#5-ship-a-ciliumnetworkpolicy>); rollout and debugging are in [Security Policies](<https://homelab.wlkr.ch/platform/security-policies/#network-policies>).

| Rule | Why |
| --- | --- |
| Ingress from the namespace, from `host` and `remote-node`; egress to the namespace | The rules every policy carries: [What every policy contains](<https://homelab.wlkr.ch/platform/security-policies/#what-every-policy-contains>) |
| Ingress on 3000 from `ingress` | The public site and `/admin`; the site is meant to be read by people Authentik has never heard of |
| Ingress from Prometheus on 9187, `GET /metrics` only | The database's metrics. Payload exposes none |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](<https://homelab-apps.wlkr.ch/conventions/#sync-stuck-on-the-database>) |
| Egress to the namespace | The site renders from its own database and serves its own uploads |
| Egress from the app to `auth.k8s.wlkr.ch` on 443 and to the Authentik server pods on 9000 | The token and userinfo calls of a sign-in. The name resolves to the Gateway, `world` to Cilium, and the Gateway's Envoy then checks the pod it picks, so both halves are needed, as for [OpenCloud](<https://homelab-apps.wlkr.ch/opencloud/#network-policy>) |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise. The object store for WAL and base backups is the platform's `cnpg-backups` policy, see [CloudNativePG → Backups](<https://homelab.wlkr.ch/platform/cloudnative-pg/#backups>) |

### Secrets

`kv/advent-wollbi/config`, `kv/advent-wollbi/seed` and `kv/advent-wollbi/oidc` hold one value each, each written once by a `PushSecret` in `secrets.yaml` and never overwritten — see [Generated secrets](<https://homelab.wlkr.ch/platform/openbao/#generated-secrets>).

| Key | Read as |
| --- | --- |
| `payload-secret` | `PAYLOAD_SECRET`: signs the editor sessions |
| `seed-token` | `SEED_TOKEN`: what the seed hook authenticates with, so the hook never holds the key that signs sessions |
| `client-secret` in `kv/advent-wollbi/oidc` | `OIDC_CLIENT_SECRET`, and Authentik's copy for the provider through the platform store |

## Usage

### Editing

`https://advent.wollbi.ch/admin`, then **Mit Authentik anmelden**. Members of `wollbi-editors` get a Payload editor on their first sign-in, matched by email; add someone to the group in Authentik to make them an editor. Pages are made of three blocks, which are the three shapes the Pelican pages had: prose, a run of images under a heading, and a download.

## Health check

```bash
kubectl -n advent-wollbi get pods
kubectl -n advent-wollbi get cluster advent-wollbi-db
kubectl -n advent-wollbi logs job/advent-wollbi-seed
curl -sI https://advent.wollbi.ch/ | head -1
```

The seed Job's log is the whole migration report: `{"seeded":true,...}` on the first run and `{"seeded":false,"reason":"pages already exist"}` on every one after it. The Job lives for `ttlSecondsAfterFinished` in `seed-job.yaml`; after that the report is in [Loki](<https://homelab.wlkr.ch/platform/logging/#usage>) as `{namespace="advent-wollbi", container="seed"}`.

## Pitfalls

> [!WARNING]
>
> **The hostname is not `k8s.wlkr.ch`**
>
> This site is on a second domain. It needs the `wollbi.ch` listener and certificate on the apps Gateway and `wollbi.ch` in external-dns' `domainFilters`, all in the platform repository. Without them the route exists, resolves to nothing and serves no certificate.

- **A new field needs a migration.** The Postgres adapter ignores schema push in production, so a collection change that works on a laptop does nothing here until `payload migrate:create` has been run and committed in the site repository.
- **The uploads volume and the database restore together.** The uploads come back from a Velero night, the database from its WAL archive; restore the database to that night's backup time ([Point-in-time restore](<https://homelab.wlkr.ch/platform/cloudnative-pg/#point-in-time-restore>)), or records point at files that are gone.
- **The site is seasonal and the cluster is not.** Nothing scales it down in January; it is one small pod and one small database all year, which is cheaper than remembering to turn it back on in November.
