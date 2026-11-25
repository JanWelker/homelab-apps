# Conventions

Rules every directory in this repository follows, each with its reason. [Adding a Workload](<https://homelab.wlkr.ch/development/add-workload/>) in the platform documentation has the templates.

## Structure

One directory per application, named after it, containing exactly one `application.yaml` — a complete ArgoCD `Application`, not a fragment. The `apps` ApplicationSet in the [homelab](<https://github.com/JanWelker/homelab>) repository generates one Application per `*/application.yaml` it finds here, so adding a directory adds an application.

Everything beside `application.yaml` is what that Application deploys, which is why every Application excludes it from its own source:

```yaml
    directory:
      exclude: "application.yaml"
```

Exception: in the `claude-*` sessions only the directory source carries it, because their OCI chart source has no directory to act on; see [Claude agents](<https://homelab-apps.wlkr.ch/claude-agents/index.md#configuration>).

## The rules

### 1\. `project: apps`

The ApplicationSet fails the whole set rather than generate a workload in the `infra` or `system` project, which are authorised against destinations a workload has no business reaching.

### 2\. Official upstream sources only

The vendor's own Helm chart, or the vendor's own container image, never a repackager's. Dependency-Track publishes its own chart; Home Assistant publishes none, so it is plain manifests around the official `ghcr.io/home-assistant/home-assistant` image. A chart from a new repository needs the `apps` project's `sourceRepos` and the repo-server's egress policy extended in the platform first, or the Application reads `ComparisonError` ([Projects](<https://homelab.wlkr.ch/platform/argocd/#projects>)).

The repository owner's own chart wrapping their own image is allowed, as with the Flowscape images and the `agent-mooring` chart.

Pin every version. No `latest`, no floating tags. Renovate moves them; release age and schedule come from the shared preset `renovate.json` extends (`github>JanWelker/renovate-config`), which a fork inherits unless it replaces that line, and the owner's own images move at once. `image-scan.yaml` is the [platform's image gate](<https://homelab.wlkr.ch/development/maintenance/#ci-workflows>).

> [!WARNING]
>
> **Renovate and image fields**
>
> A custom regex manager for an image field needs `autoReplaceStringTemplate`, or digest pinning fails with `update failure` and takes the shared `renovate/pin-dependencies` branch down with it. A field holding a bare tag has no room for a digest and needs `pinDigests: false` instead. See [Manager rules](<https://homelab.wlkr.ch/development/maintenance/#manager-rules>) and [renovate\#24942](<https://github.com/renovatebot/renovate/issues/24942>).

### 3\. PostgreSQL is always a CloudNativePG `Cluster`

Never the database a chart bundles. Disable it (`internalDatabase.enabled: false`, `postgresql.enabled: false`) and point the chart at a `Cluster` in the same namespace through its external-database settings.

A single-instance `Cluster` sets `enablePDB: false`: the operator's `<cluster>-primary` PodDisruptionBudget otherwise never allows an eviction, so a drain of that node hangs until Kured's timeout and the node is never rebooted.

Every `Cluster` sets `smartShutdownTimeout: 15`, and one with replicas `primaryUpdateMethod: switchover`; the reasoning is in [the contract](<https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract>). Each application holds a connection pool, so the default smart shutdown only lengthens every restart and move.

Use the `standard` image: `system` only adds the in-core Barman Cloud the plugin replaces and is deprecated. Ship a `PodMonitor` instead of the deprecated `monitoring.enablePodMonitor`.

Every `Cluster` gets a `backup.yaml` beside it, the [stanza from the platform](<https://homelab.wlkr.ch/platform/cloudnative-pg/#backing-up-a-database>) with the `Cluster`'s name and namespace filled in, and the `plugins` entry in the `Cluster`. Its S3 user writes only its own prefix of the bucket the [off-cluster copy](<https://homelab.wlkr.ch/operations/backups/#off-cluster-copy>) pulls, and is named `<namespace>.<purpose>` or the platform refuses it. So is a `Cluster` without the `plugins` entry, unless it carries `homelab.wlkr.ch/backup-exempt` with the reason. Velero's nightly snapshot restores only to that night; the WAL archive to any second.

The operator writes a `<cluster-name>-app` Secret with `username`, `password`, `host`, `port`, `dbname` and a ready-assembled `uri`. Consume those keys; never copy the value into Git or OpenBao.

Give the `Cluster` an earlier sync wave than the application. ArgoCD has a health check for `postgresql.cnpg.io/Cluster`, so the wave waits for a working database, not merely a created one:

```yaml
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

Annotate it `Prune=false`, as the PVC and the namespace are: deleting a `Cluster` deletes the volumes it owns. A chart-rendered PVC needs the same annotation through the chart's values; `helm.sh/resource-policy: keep` only survives deleting the Application, not a prune.

### 4\. Own your namespace

Ship a `namespace.yaml` at sync wave `-2` carrying the three [Pod Security Admission](<https://homelab.wlkr.ch/platform/security-policies/#pod-security-admission>) labels; `CreateNamespace=true` alone leaves an unlabelled namespace that runs at `privileged`. Set `enforce` to what the application needs and `audit`/`warn` stricter, so the violations a tighter level would catch stay visible.

Annotate it `Prune=false`: pruning a `Namespace` deletes every PVC inside it.

Exception: the `claude-*` sessions ship no namespace: the platform declares each `claude-<session>` and refuses it from here; see [Claude agents](<https://homelab-apps.wlkr.ch/claude-agents/index.md#configuration>).

### 5\. Ship a `CiliumNetworkPolicy`

Not a plain `NetworkPolicy`, which blocks the kubelet's health probes. Every policy needs `fromEntities: [host, remote-node]` for those probes, one rule for the way users arrive, the namespace itself on both halves (`fromEndpoints: [{}]`, `toEndpoints: [{}]`), and every outside name as `toFQDNs`. No DNS rule: the platform grants every pod its lookups through the proxy in one cluster-wide policy, so a copy here only hides what the namespace adds — see [Security Policies → Cluster-wide rules](<https://homelab.wlkr.ch/platform/security-policies/#cluster-wide-rules>). The arrival rule depends on rule 6: `fromEntities: [ingress]` where the Gateway reaches the pod directly, or the Authentik server pods and nothing else where the outpost sits in front, so a request cannot skip it.

Put it at sync wave `-2`, with the namespace:

```yaml
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
```

At the default wave it lands after the `Cluster` from rule 3, and a rule the `Cluster` needs in order to go Healthy can never unblock the wave it is stuck behind — see [Sync stuck on the database](<#sync-stuck-on-the-database>).

Exception: the `homelab` session's policy allows every public address as a `toCIDRSet` instead of names, because a diagnosis fetches whatever it needs and a name list would be a firewall change per lookup; see [Claude agents → Network policy](<https://homelab-apps.wlkr.ch/claude-agents/index.md#network-policy>).

### 6\. Authentication is Authentik's, not the application's

Which shape applies is decided by what the application supports:

- **It speaks OIDC.** Configure it against Authentik, hide the local login form, and keep at most one local admin as break-glass. Dependency-Track is the worked example.
- **It does not.** Point its `HTTPRoute` at `authentik-server` in the `authentik` namespace, so the outpost authenticates in front of it. Home Assistant is the worked example; where the application has its own login this is defence in depth, not single sign-on.
- **It has no browser session.** An API carries its own credential, since an outpost would answer its caller with a login page: [Knead Time](<https://homelab-apps.wlkr.ch/kneadtime/index.md>) has none and CORS admits one origin, the [Shot Timer bridge](<https://homelab-apps.wlkr.ch/shot-bridge/index.md>) checks its own bearer key, and the [Claude agents](<https://homelab-apps.wlkr.ch/claude-agents/index.md>) admit SSH keys on a TLS passthrough.

The OIDC provider's blueprint lives in the platform repository, because a blueprint has full access to Authentik; see [Authentik → Where a blueprint lives](<https://homelab.wlkr.ch/platform/authentik/#where-a-blueprint-lives>). The client credentials are generated here, by the generator and `PushSecret` in the application's `secrets.yaml` (rule 7), and read on Authentik's side by an `ExternalSecret` there, where the outpost's provider list and any `referencegrant.yaml` entry also live, so going behind SSO is deliberately two pull requests.

Because blueprint discovery is asynchronous, anything that configures itself against the provider must tolerate it not existing yet: fail soft and log. Watch for SSRF guards, too: `auth.k8s.wlkr.ch` resolves to a private address, which an application that refuses local addresses rejects.

**Account keys rest on usernames staying put.** Dependency-Track keys an account on `preferred_username`, which is the Authentik username, so a user who could rename themselves to someone else's name would log in as that account. The platform's Authentik brand therefore uses a user settings flow without a username field; see [User settings flow](<https://homelab.wlkr.ch/platform/authentik/#user-settings-flow>). A new application keys on `sub` instead. An existing one stays on `preferred_username`, because switching gives every account a new ID and orphans its data.

**Use `auth.k8s.wlkr.ch`**, Authentik's only hostname, for the discovery URI and the redirect alike: the `iss` claim is the name the token was issued through, and a client that mixes names fails every login — see [One hostname](<https://homelab.wlkr.ch/platform/authentik/#one-hostname>).

### 7\. Real secrets come from OpenBao

An `ExternalSecret` reading `kv/<app>/config`, with a comment at the top of the file naming what writes it. It and any `PushSecret` name the `openbao-apps` store, and `secrets.yaml` starts with an `external-secrets-vault` ServiceAccount at sync wave `-2`: the store logs in as it and reaches `kv/<namespace>/` only, so `<app>` is the namespace — see [Kubernetes auth](<https://homelab.wlkr.ch/platform/openbao/#kubernetes-auth>). The store admits only the namespaces listed in the platform's `cluster-secret-store.yaml`, so a new application's `ExternalSecret` and `PushSecret` fail until a platform pull request adds the namespace and `make bao-policies` runs. Random values — session keys, admin passwords, OIDC client pairs — come from a `Password` generator and a `PushSecret` at the end of the same `secrets.yaml`, at sync wave `-2` so they land before the `ExternalSecret` at `-1` — see [Generated secrets](<https://homelab.wlkr.ch/platform/openbao/#generated-secrets>). A value from an account outside the cluster, such as a model API key, is typed in with `make bao-secrets` in the platform repository, into a path of its own: a `bao kv put` replaces a path wholesale and would take the generated keys with it. Database passwords are neither, because CloudNativePG generates them (rule 3).

OIDC client credentials go in the application's own `kv/<app>/config`, never under `kv/authentik/config`, where that wholesale replace would make adding an application an Authentik outage.

Exception: the `claude-*` sessions' `ExternalSecret`s come from the chart and read `kv/claude-<session>/github`, the prefix of their own namespace; see [Claude agents → Secrets](<https://homelab-apps.wlkr.ch/claude-agents/index.md#secrets>).

### 8\. The shared `syncPolicy`

`automated` with `prune` and `selfHeal`, plus `retry` with a limit of 10 and a 30s backoff up to 5m, and `syncOptions` with `ServerSideApply=true`, copied from any sibling but the `claude-*` Applications, which leave the option out. ArgoCD never re-attempts a failed sync of the same revision without `retry`, and a workload that lands a minute before the platform resource it names would otherwise stay failed until someone ran `argocd app sync`. Server-side apply is what every platform Application uses, so the two repositories diff and apply the same way.

## What you do not have to write

The platform handles all of this; adding your own is the usual mistake:

| You want | You write | The platform does |
| --- | --- | --- |
| A hostname | An `HTTPRoute` on `apps-gateway`, or on `infra-gateway` for LAN and VPN only, which admits named namespaces, so a platform pull request first | external-dns publishes the `apps-gateway` record to Route53 |
| HTTPS | Nothing | Each listener holds a wildcard certificate; see [Gateway API](<https://homelab.wlkr.ch/platform/gateway-api/#configuration>) |
| Storage | `storageClassName: rook-ceph-block` | Rook-Ceph replicates it three ways |
| Logs | Nothing | Alloy ships stdout to Loki |
| Backups of a PVC | Nothing | Velero snapshots it nightly; restoring is in [Backups & Recovery](<https://homelab.wlkr.ch/operations/backups/>) |
| Backups of a database | `backup.yaml` and a `plugins` entry (rule 3) | WAL archived continuously, a base backup nightly, to the database's own prefix of `offsite` |
| Metrics | A `ServiceMonitor` or `PodMonitor` | Prometheus scrapes it |
| Priority under memory pressure | Nothing for a service, `priorityClassName: batch` for a Job or CronJob | Services rank below the platform and above its monitoring; any other class is refused, see [Priority classes](<https://homelab.wlkr.ch/platform/#priority-classes>) |

## Writing an `HTTPRoute`

The API server fills in defaults for what a route leaves out, and ArgoCD reports every filled-in field as drift unless the platform tells it to look away, which covers less than you might expect:

| Write out | Because ArgoCD |
| --- | --- |
| `group: gateway.networking.k8s.io` and `kind: Gateway` on each `parentRefs` entry | ignores neither |
| Every rule's `matches`, the catch-all's `PathPrefix /` included, once a route has more than one rule | forgives a missing `matches` only on the first rule |

A route that leaves either out reports `OutOfSync` forever while working fine. `sectionName` on the `parentRefs` entry picks the listener, and a listener pins one hostname pattern, so the wollbi sites name their own; the table is [Gateway API → Configuration](<https://homelab.wlkr.ch/platform/gateway-api/#configuration>).

A route on `apps-gateway` also carries a `ResponseHeaderModifier` that sets `Strict-Transport-Security`, `X-Content-Type-Options: nosniff` and `X-Frame-Options: SAMEORIGIN`; copy it from [`flowscape/httproute.yaml`](<https://github.com/JanWelker/homelab-apps/blob/main/flowscape/httproute.yaml>). It `set`s rather than `add`s, since the Authentik outpost already sends them and a duplicated frame header is invalid. HSTS names no `includeSubDomains` or `preload`, because other names under these domains are not served from here. A chart-rendered route takes it as `httpRoute.filters`.

## Behind the Gateway

Traffic arrives from Cilium's Envoy, not the client, and TLS ends at the Gateway. Set the application's trusted-proxies and overwrite-protocol settings, or it sees the proxy's address, builds `http://` links and loops on the login redirect.

## Sync stuck on the database

The default-deny policy must allow the `cnpg-system` namespace to reach the database pod on port 8000, the instance manager's status endpoint the operator polls, and the policy must sit at sync wave `-2` with the namespace. Its `kube-apiserver` egress selects `cnpg.io/cluster: <cluster>`, not `cnpg.io/podRole: instance`: the operator's `join` and `initdb` Jobs carry `cnpg.io/jobRole` instead, and without the API they wait forever, so a new replica stays at `Creating a new replica`. At the default wave it lands after the `Cluster` at `-1`, and a wave that never finishes never applies the rule that would unblock it.

1. **Symptom.** Postgres serves the application and `kubectl get cluster` reads `1/1`, but the phase is `Instance Status Extraction Error: HTTP    communication issue`. The Application is `Synced` with health `Unknown` and every entry in `status.resources` lacks a health field: a genuinely unhealthy workload names the failing resource.

   ```text
   $ kubectl get application -n argocd <app> -o jsonpath='{.status.operationState.message}'
   waiting for healthy state of postgresql.cnpg.io/Cluster/<app>-db
   ```
2. **Confirm the drop** from the node running the database:

   ```bash
   pod="$(kubectl -n kube-system get pod -l k8s-app=cilium --field-selector spec.nodeName=<node> -o name)"
   kubectl -n kube-system exec "$pod" -c cilium-agent -- \
     hubble observe --verdict DROPPED --from-namespace cnpg-system --last 20
   ```
3. **Check which waves ran.** If `CiliumNetworkPolicy` is missing while `Cluster` reads `Running`, the policy is behind the thing it should unblock:

   ```bash
   kubectl get application -n argocd <app> \
     -o jsonpath='{range .status.operationState.syncResult.resources[*]}{.kind}{"\t"}{.hookPhase}{"\n"}{end}'
   ```
4. **Fix.** Put the policy at wave `-2`, then terminate the stuck operation, which never picks up the new revision on its own:

   ```bash
   argocd app terminate-op <app>
   ```

   The CLI login is [Argo CD → CLI access](<https://homelab.wlkr.ch/platform/argocd/#cli-access>). The next sync applies the policy first and the `Cluster` goes Healthy.
