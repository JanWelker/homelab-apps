---
description: "fest.wollbi.ch on the cluster: the Wollbi-Fescht site as Payload CMS on Next.js, public at the root, with editors signing in to /admin through Authentik."
---

# Wollbi-Fescht

[fest.wollbi.ch](https://fest.wollbi.ch) is the invitation to the street's
summer party, and the archive of every invitation since 1987. It is the same
application as [Wollbi Adventsfenster](advent-wollbi.md), with its own content,
built in [JanWelker/fest.wollbi.ch](https://github.com/JanWelker/fest.wollbi.ch)
(private), so its upstream is our own — per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).
This page holds what differs; every other row is on the advent page.

## At a glance

| | |
| --- | --- |
| URL | [fest.wollbi.ch](https://fest.wollbi.ch) — public, no login |
| Authentication | Payload signs editors in through Authentik over OIDC, members of `wollbi-editors` only; no local accounts; `/seed` redirects to `/` |
| Storage | A PVC for what editors upload after the seed |
| Database | CloudNativePG `Cluster` `fest-wollbi-db` |
| Secrets | `kv/fest-wollbi/config`, `kv/fest-wollbi/seed` and `kv/fest-wollbi/oidc` in OpenBao |
| Files | [`fest-wollbi/`](https://github.com/JanWelker/homelab-apps/tree/main/fest-wollbi) |

## Configuration

[Wollbi Adventsfenster → Configuration](advent-wollbi.md#configuration)
applies with `fest-wollbi` for `advent-wollbi`, except two rows: the media
row is the advent site's alone, and `fest-wollbi-db` runs
without a replica
([`database.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/fest-wollbi/database.yaml)),
so the single-instance case of
[Conventions → rule 3](conventions.md#3-postgresql-is-always-a-cloudnativepg-cluster)
applies and a drain takes the site down for the move.

### Seeding

The same `PostSync` hook as
[Wollbi Adventsfenster → Seeding](advent-wollbi.md#seeding). On an empty
database it imports every file in the site repository's `public/seed/images/`
as media, including the ones no page references, because the archive is the
reason the site exists, then writes three pages: Willkommen, Info and the
Einladungsarchiv.

### OIDC

As [Wollbi Adventsfenster → OIDC](advent-wollbi.md#oidc), with `client_id`
`fest-wollbi`.

### Network policy

[`fest-wollbi/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/fest-wollbi/networkpolicy.yaml)
carries the same rules as the advent site's; the reasons are in
[Wollbi Adventsfenster → Network policy](advent-wollbi.md#network-policy).

### Secrets

The three paths in [At a glance](#at-a-glance) hold the same keys as
[Wollbi Adventsfenster → Secrets](advent-wollbi.md#secrets).

## Usage

`https://fest.wollbi.ch/admin`, then as
[Wollbi Adventsfenster → Editing](advent-wollbi.md#editing).

## Health check

```bash
kubectl -n fest-wollbi get pods
kubectl -n fest-wollbi get cluster fest-wollbi-db
kubectl -n fest-wollbi logs job/fest-wollbi-seed
curl -sI https://fest.wollbi.ch/ | head -1
```

The seed log reads as on
[Wollbi Adventsfenster → Health check](advent-wollbi.md#health-check); in
[Loki](https://homelab.wlkr.ch/platform/logging/#usage) it is
`{namespace="fest-wollbi", container="seed"}`.

## Pitfalls

The [Wollbi Adventsfenster pitfalls](advent-wollbi.md#pitfalls) on the
second domain, migrations and restores apply here too. One more:

- **Deleting `kv/fest-wollbi/config` logs the editors out.**
