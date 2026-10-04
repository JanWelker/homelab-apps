---
description: "advent.wollbi.ch on the cluster: the Adventsfenster site as Payload CMS on Next.js, public at the root and behind the Authentik outpost at /admin."
---

# Wollbi Adventsfenster

[advent.wollbi.ch](https://advent.wollbi.ch) is the invitation to the street's
advent windows: the flyer, the dates and the calendar file to import. It was a
Pelican site until the pages became rows in a database: the content is now
edited at `/admin` and the repository holds the application, not the text. The
image is built in
[JanWelker/advent.wollbi.ch](https://github.com/JanWelker/advent.wollbi.ch),
so its upstream is our own — per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [advent.wollbi.ch](https://advent.wollbi.ch) — public, no login |
| Authentication | Authentik proxy outpost on `/admin` only, in front of Payload's own login |
| Storage | A PVC for what editors upload after the seed |
| Database | CloudNativePG `Cluster` `advent-wollbi-db` |
| Secrets | `kv/advent-wollbi/config` in OpenBao |
| Files | [`advent-wollbi/`](https://github.com/JanWelker/homelab-apps/tree/main/advent-wollbi) |
| Source | [JanWelker/advent.wollbi.ch](https://github.com/JanWelker/advent.wollbi.ch) |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests around our own image | One Next.js process with one port and one database; the site repository's README is the whole deployment contract |
| The namespace enforces `restricted` | The image is distroless and runs as uid 65532, its `nonroot` user, with a read-only root filesystem; the two things it writes, the uploads and Next.js' render cache, are volumes. There is no shell in it, so `kubectl exec` is for `node -e`, not for poking around |
| `DATABASE_URL` from `advent-wollbi-db-app`, key `uri` | Payload wants one connection string and CloudNativePG assembles it; see [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract) |
| `PAYLOAD_SECRET` from OpenBao | It signs every editor session. Generated in the cluster it would change on every rebuild and log everyone out |
| `NEXT_PUBLIC_SERVER_URL` | The origin Payload trusts for CSRF and builds absolute URLs from. TLS ends at the Gateway, so the pod's own address is the wrong answer — see [Behind the Gateway](conventions.md#behind-the-gateway) |
| An `emptyDir` on `/app/.next/cache` | Next.js writes its render cache at runtime and the root filesystem is read-only. It is a cache: losing it on a restart costs one slow first request |
| Two rules on one `HTTPRoute` | The site is an invitation to the neighbours, so `/` reaches the app directly. `/admin` goes through the outpost, and so does `/outpost.goauthentik.io`, where the outpost finishes the login on this hostname. A longer path prefix wins in Gateway API, so the order of the rules does not matter. The cross-namespace `backendRef` works only because the platform's `referencegrant.yaml` names this namespace |
| The media collection accepts PDFs and `text/calendar` | The flyer and the `.ics` are content here, not attachments; as uploads the CMS knows about them, where the Pelican site had them as links in prose that outlive the file |
| `/healthz` answers without the database | A database outage should show as an empty page, not as a pod the kubelet restarts in a loop |

### Seeding

The Pelican content is imported once, by a `PostSync` hook that `curl`s a
route inside the image. The route is part of the build, so there is no second
image to keep in step; it refuses without the secret the pod already holds,
and does nothing once a page exists. That is what makes it safe to run after
every sync rather than once by hand.

What it does, in order, and only on an empty database:

1. Creates the first editor from `SEED_ADMIN_EMAIL` and the password in
   OpenBao.
2. Imports every file in the site repository's `public/seed/images/` as
   media — ten of them, including the flyers of 2023 and 2024 and the 2024
   calendar, which the current site no longer links but which are the record
   of those years.
3. Writes the two pages: Willkommen and Info.

Afterwards the database is the source of truth and the seed is a no-op.

### Network policy

Every rule in
[`advent-wollbi/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/advent-wollbi/networkpolicy.yaml),
and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

| Rule | Why |
| --- | --- |
| Ingress on 3000 from `ingress` | The public site; it is meant to be read by people Authentik has never heard of |
| Ingress on 3000 from the Authentik server pods, with an L7 `http` rule | `/admin` through the outpost |
| Ingress from Prometheus on 9187, `GET /metrics` only | The database's metrics. Payload exposes none |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy and the sync deadlocks. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |
| Egress to the namespace, and nothing else at all | The site renders from its own database and serves its own uploads. There is no `toFQDNs` block, which is the shortest way to say a public site never calls out |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

## Usage

### Editing

`https://advent.wollbi.ch/admin` — Authentik first, then Payload's own login.
Pages are made of three blocks, which are the three shapes the Pelican pages
had: prose, a run of images under a heading, and a download.

### Secrets

`kv/advent-wollbi/config` holds two values, written once by the `PushSecret` in
`secrets.yaml` and never overwritten — see [Generated secrets](https://homelab.wlkr.ch/platform/openbao/#generated-secrets).

| Key | Read as |
| --- | --- |
| `payload-secret` | `PAYLOAD_SECRET`: signs the editor sessions, and the token the seed hook authenticates with |
| `admin-password` | The first editor's password, read only while the database is empty |

## Health check

```bash
kubectl -n advent-wollbi get pods
kubectl -n advent-wollbi get cluster advent-wollbi-db
kubectl -n advent-wollbi logs job/advent-wollbi-seed
curl -sI https://advent.wollbi.ch/ | head -1
```

The seed Job's log is the whole migration report: `{"seeded":true,...}` on the
first run and `{"seeded":false,"reason":"pages already exist"}` on every one
after it.

## Pitfalls

!!! warning "The hostname is not `k8s.wlkr.ch`"
    This site is on a second domain. It needs the `wollbi.ch` listener and certificate on the apps Gateway and `wollbi.ch` in external-dns' `domainFilters`, all in the platform repository. Without them the route exists, resolves to nothing and serves no certificate.

- **A new field needs a migration.** The Postgres adapter ignores schema push
  in production, so a collection change that works on a laptop does nothing
  here until `payload migrate:create` has been run and committed in the site
  repository.
- **The uploads volume and the database are one backup.** A restore of one
  without the other leaves records pointing at files that are gone.
- **The site is seasonal and the cluster is not.** Nothing scales it down in
  January; it is one small pod and one small database all year, which is
  cheaper than remembering to turn it back on in November.
