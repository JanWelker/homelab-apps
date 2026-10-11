---
description: "Pull request previews of the two wollbi sites: one namespace, database and hostname per pull request labelled preview, deleted when it closes."
---

# Pull request previews

A pull request on [advent.wollbi.ch](advent-wollbi.md) or
[fest.wollbi.ch](fest-wollbi.md) labelled `preview` runs as its own copy of
the site, with a freshly seeded database, at
`<site>-pr-<number>.k8s.wlkr.ch`. The `previews` ApplicationSet in the
platform repository generates it; its token and generator are described in
[Argo CD → Pull request previews](https://homelab.wlkr.ch/platform/argocd/#pull-request-previews).

## At a glance

| | |
| --- | --- |
| URL | `https://advent-wollbi-pr-<n>.k8s.wlkr.ch`, `https://fest-wollbi-pr-<n>.k8s.wlkr.ch` — public, `noindex` |
| Namespace | `<site>-pr-<n>`, deleted with everything in it when the pull request closes or loses the label |
| Image | `ghcr.io/janwelker/<site>-ch:sha-<head SHA>`, pushed by the site's `push-image.yml` for every pull request |
| Files | [`advent-wollbi/preview/`](https://github.com/JanWelker/homelab-apps/tree/main/advent-wollbi/preview), [`fest-wollbi/preview/`](https://github.com/JanWelker/homelab-apps/tree/main/fest-wollbi/preview) |

## Configuration

Each `preview/` directory is a Kustomize base copied from the production
manifests beside it. The ApplicationSet sets the namespace, the image tag and
the hostname; the base holds placeholders for all three.

| Setting | Why |
| --- | --- |
| Opt-in through the `preview` label | Each preview is a database and a Next.js process; Renovate's pull requests would otherwise run several at all times |
| Secrets from a `Password` generator, `refreshInterval: "0"` | Nothing of a preview belongs in OpenBao; the values are generated once and die with the namespace |
| No `Prune=false` on the namespace or the `Cluster` | Closing the pull request is meant to delete the data |
| Uploads on an `emptyDir` | A preview shows the seed; uploads made while testing need not outlive the pod |
| Under `*.k8s.wlkr.ch` on the `https` listener | The platform's wildcard certificate and external-dns already cover it, so a preview needs no platform change |
| No Authentik outpost on `/admin` | An outpost provider names one hostname, and preview hostnames come and go; Payload's own login is the gate |
| `X-Robots-Tag: noindex, nofollow` | A public preview must not compete with the real site in search results |
| The image keeps production's tag and digest in the base | Renovate moves it with production; the ApplicationSet replaces both with the pull request's tag |

## Usage

1. Add the `preview` label to the pull request.
2. Wait for the `Push image` check, then up to a minute for the Application.
3. Open `https://<site>-pr-<n>.k8s.wlkr.ch`. To log in at `/admin` as the
   seeded editor:

    ```bash
    kubectl -n advent-wollbi-pr-<n> get secret advent-wollbi-config \
      -o jsonpath='{.data.admin-password}' | base64 -d
    ```

Every push to the pull request moves the image tag and redeploys. The database
is seeded once and kept across pushes.

## Health check

```bash
kubectl -n argocd get applications | grep -- -pr-
kubectl -n argocd get applicationset previews -o jsonpath='{.status.conditions}'
```

## Pitfalls

- **A later push meets the database an earlier one seeded.** To start from
  scratch, remove the label, wait for the namespace to go, and add it again.
- **A pull request from a fork gets no preview.** Its workflow cannot push to
  GHCR, so the image never exists and the pod stays in `ImagePullBackOff`.
- **Production changes reach the preview base only by hand.** A new setting in
  `<site>/deployment.yaml` belongs in `<site>/preview/deployment.yaml` too.
