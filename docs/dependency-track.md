---
description: "Dependency-Track on the cluster: the official chart, an external CloudNativePG database, Authentik OIDC, and a nightly job that feeds it every SBOM Trivy Operator already produces."
---

# Dependency-Track

[Dependency-Track](https://dependencytrack.org/) keeps a software bill of
materials for every image the cluster runs and re-checks each one against the
vulnerability feeds every day, so a new CVE shows up against images that were
already scanned, not only the next time Trivy looks. Upstream publishes the
[`dependency-track` chart](https://github.com/DependencyTrack/helm-charts/tree/main/charts/dependency-track),
so this is that chart with an external database, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only);
the network policy, the database, the Authentik blueprint and the upload job
come from a second source pointing at this repository.

The SBOMs are not generated here. The platform's
[Trivy Operator](https://homelab.wlkr.ch/platform/trivy-operator/) writes one
CycloneDX `SbomReport` per running container, and the [upload job](#sbom-upload)
hands them over once a night. Trivy answers what is in the images today;
Dependency-Track answers what changed, which images share a component, and
whether a policy holds across the portfolio.

## At a glance

| | |
| --- | --- |
| URL | [sbom.k8s.wlkr.ch](https://sbom.k8s.wlkr.ch) |
| Authentication | Authentik OIDC, code flow with PKCE; `admin` kept as break-glass |
| Storage | A PVC for uploaded BOM files and the mirrored feeds |
| Database | CloudNativePG `Cluster` `dependency-track-db` |
| Secrets | `kv/dependency-track/config` and `kv/dependency-track/sbom-upload` in OpenBao |
| Files | [`dependency-track/`](https://github.com/JanWelker/homelab-apps/tree/main/dependency-track) |

## Configuration

The chart values in `application.yaml` that are not defaults:

| Setting | Why |
| --- | --- |
| `database.existingSecret: dependency-track-db-app` | CloudNativePG's generated credentials carry the `username` and `password` keys the chart mounts as files; see [the contract](https://homelab.wlkr.ch/platform/cloudnative-pg/#the-contract). The JDBC URL names the `-rw` Service |
| `secretManagement.database.kek` from `dependency-track-config` | The key that encrypts every secret Dependency-Track stores in its database, API tokens for the feeds included. It must survive a rebuild, so it is generated into OpenBao, never by the chart. See [Secrets](#secrets) |
| `fileStorage.local.existingClaim` | The chart's own PVC carries only `helm.sh/resource-policy: keep`, which a prune ignores; `pvc.yaml` carries `Prune=false` like every other volume here |
| `DT_TELEMETRY_SUBMISSION_DEFAULT_ENABLED: "false"` | No phone-home. The property seeds the setting once, so it has to be off before the first start; the egress policy would drop the request anyway |
| `DT_OIDC_*` and the frontend's `OIDC_*` | Both halves must name the same issuer and client ID; the API server validates the ID token the browser obtained. `preferred_username` is Authentik's username claim, and `groups` arrives with the `profile` scope, so team membership follows Authentik's groups. See [OIDC](#oidc) |
| `apiServer.web.resources`, 1Gi requested, 3Gi limit | The JVM sizes its heap from the limit. Upstream recommends 8Gi for production; the portfolio here is a few hundred small images |
| `serviceMonitor.namespace: dependency-track` | The chart defaults to the `monitoring` namespace, which the `apps` project may not write to. Prometheus reads it from here like every other application's |
| `httpRoute` on `apps-gateway` | The chart's route sends `/api` to the API server and everything else to the frontend on one hostname, so the frontend's `API_BASE_URL` stays empty and the browser uses relative URLs |
| `revisionHistoryLimit: 2` on both Deployments | Superseded ReplicaSets keep their Trivy config-audit reports until garbage collection; the chart keeps five |

### Network policy

Every rule in `dependency-track/networkpolicy.yaml`, and why it is there. The
shape is [Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy).

| Rule | Why |
| --- | --- |
| Ingress on 8080 from `ingress` | The Gateway reaches the API server and the frontend directly; the login is OIDC, so no outpost sits in front |
| Ingress from Prometheus on 9000 and 9187, `GET /metrics` only | The API server's management port and the database's exporter |
| Ingress from `cnpg-system` on 8000 | The operator polls the instance manager there; without the rule the `Cluster` never goes Healthy. See [Sync stuck on the database](nextcloud.md#sync-stuck-on-the-database) |
| Egress from the API server to Authentik | Discovery, the signing keys and the userinfo endpoint, on the public name, for the same reason Nextcloud dials it: the `iss` claim is that name |
| Egress from the API server to `nvd.nist.gov`, `storage.googleapis.com`, `api.github.com`, `epss.empiricalsecurity.com` | The feeds the internal analyzer mirrors: NVD, OSV, GitHub Advisories, EPSS. GitHub stays off until a token is entered in the UI; the rule is there so entering one is the only step |
| Egress from the API server to `proxy.golang.org`, `registry.npmjs.org`, `pypi.org`, `repo1.maven.org`, `api.nuget.org`, `crates.io`, `rubygems.org` | The registries Dependency-Track asks for the latest version of a component, for the ecosystems the images here contain. The other default repositories are disabled at [first login](#first-login) rather than allowed |
| Egress from the upload job to `kube-apiserver` | It lists the `SbomReport` objects; the API it posts to is in the namespace |
| Egress from the database pod to `kube-apiserver` | The instance manager reports its status there; its liveness check fails otherwise |

### SBOM upload

`sbom-upload.yaml` is a CronJob, a ConfigMap holding the script, and a
ServiceAccount. At 05:00 it lists every `SbomReport` in the cluster and sends
each distinct image that is running, once, to `PUT /api/v1/bom` with
`autoCreate`.

| Detail | Why |
| --- | --- |
| Project name is the image reference without its tag, version is the tag | A project's version history is then Renovate's bump history, and two namespaces running the same image share one project |
| Namespaces become `namespace:<name>` tags on the project | Where a finding runs is the first question when it fires |
| Reports owned by a ReplicaSet scaled to zero are skipped | A report outlives its workload until the ReplicaSet is garbage-collected, and a superseded revision is not part of what runs. If the platform's grant lacks `replicasets`, the job says so and uploads everything |
| `isLatest` goes to the highest version that is running | Two versions of one image can run at once, and the flag otherwise lands on whichever was uploaded last |
| Two digests under one tag are one upload | They are one project version; the namespaces of both become its tags |
| Reads `report.components` from the report, unchanged | Trivy Operator already writes CycloneDX; Dependency-Track accepts the same document, `specVersion` 1.7 included |
| The `ClusterRole` that lets it list reports and ReplicaSets is the platform's | The `apps` project may not create cluster-scoped RBAC, and who may read Trivy's findings is the platform's call. It is `sbom-readers.yaml` next to the operator in the homelab repository |
| The API key is `optional` on the container, and its `ExternalSecret` is at sync wave 1 | A missing Secret would leave the pod in `CreateContainerConfigError`, and a `Forbid` CronJob never runs again behind a Job that never finishes; the script exits 1 with the reason instead. The wave is the same argument one level up: this is the one secret only a running Dependency-Track can issue, so it is fetched after the application, never in a wave that gates it. `make bao-secrets` writes the path empty rather than leaving it absent, for the same reason |
| Runs before the platform's `findings-history` job at 06:30 | Both read the same reports; neither depends on the other |

### False positives

`false-positives.json` in the same ConfigMap names findings that are not
findings: a project, an advisory, a component and the reason. After the
uploads the job records each as a suppressed `FALSE_POSITIVE` analysis.

| Detail | Why |
| --- | --- |
| The job records them, not a person | An analysis belongs to one project version, so every new tag of the image arrives with the finding open again |
| A rule names the component by PURL without its version | The version moves with the image; the name is what collides |
| A finding raised by tonight's upload is suppressed tomorrow | Dependency-Track analyses a BOM after it has accepted it, and the job does not wait |
| Without `VULNERABILITY_ANALYSIS_UPDATE` the job says so and succeeds | The uploads are what the job is for |

### Retired projects

A project the job created and did not upload in a run is marked inactive,
since its image no longer runs. Administration → Configuration →
Maintenance then deletes it: retention there only ever acts on inactive
projects.

| Detail | Why |
| --- | --- |
| Only after a run with no failed upload and no skipped report | A run that found nothing to upload would retire the portfolio |
| Only projects with a `namespace:` tag | That is the job's mark; a project created by hand is not the job's to retire |
| Every upload asks for an active project | An image that runs again after a rollback is part of the portfolio again |
| Without `PORTFOLIO_MANAGEMENT_UPDATE` the job says so and succeeds | The uploads are what the job is for |

How many retired versions of a project stay is the retention setting's
to say, not the job's.

### OIDC

The provider is `dependency-track/authentik-blueprint.yaml`, a ConfigMap
targeted at the `authentik` namespace, mounted and discovered the way
[Nextcloud's](nextcloud.md#oidc) is. What differs:

| Blueprint field | Why |
| --- | --- |
| `client_type: public`, no `client_secret` | The frontend is a browser application and authenticates with authorization code plus PKCE; there is nowhere to keep a secret and the API server only validates the resulting ID token |
| `redirect_uris` ends in `/static/oidc-callback.html` | The page the frontend ships for the return leg |
| `client_id` from `!Env` | Authentik reads it from its own `ExternalSecret` on `kv/dependency-track/config`, the same value both Deployments read |
| A `dependency-track-admins` group | Mapped to the `Administrators` team, so the `groups` claim is what grants admin, in the shape [ArgoCD and Grafana](https://homelab.wlkr.ch/platform/authentik/#groups-and-roles) already use. The group is in the blueprint because it is the contract; who is in it stays in Authentik and out of Git |

The issuer is `https://auth.k8s.wlkr.ch/application/o/dependency-track/`,
trailing slash included: Dependency-Track compares the discovered issuer
with the configured one character for character, and Authentik's carries
the slash. Use `auth.k8s.wlkr.ch`, Authentik's only hostname; see
[One hostname](https://homelab.wlkr.ch/platform/authentik/#one-hostname).

### Secrets

Two paths. `kv/dependency-track/config` is written once by the `PushSecret`
in `secrets.yaml` and never overwritten — see [Generated secrets](https://homelab.wlkr.ch/platform/openbao/#generated-secrets); its template turns 32
generated characters into the base64 the chart wants for `kek`.
`kv/dependency-track/sbom-upload` is written by `make bao-secrets` in the
platform repository.

| Path | Key | Read by |
| --- | --- | --- |
| `kv/dependency-track/config` | `kek` | The API server, as the key encryption key for the secrets it stores |
| `kv/dependency-track/config` | `oidc-client-id` | The API server, the frontend **and** Authentik, through two `ExternalSecret`s |
| `kv/dependency-track/sbom-upload` | `api-key` | The upload job |

The API key is its own path because Dependency-Track issues it, after the
first start, and a `bao kv put` replaces a path wholesale: writing it later
into the first path would have deleted the KEK. The script asks for it and
accepts an empty answer, so the path exists before Dependency-Track can issue
a key. The database password is not here; CloudNativePG generates it.

## Usage

### First login

The first start seeds `admin` with the password `admin` and asks for a new
one. Keep the account as break-glass; everything after is Authentik.

1. Add yourself to `dependency-track-admins` in Authentik. The blueprint
   creates the group and the mapping to the `Administrators` team is under
   Administration → Access Management → OpenID Connect Groups; team
   synchronization grants it on the next login.

    !!! danger "A team with no mapped group is emptied at every login"
        `synchronizeTeamMembership` removes an OIDC user from every team
        that has no mapped OpenID Connect group, so adding someone to a team
        by hand holds only until they log in again. The mapping, not the
        membership, is what lasts.
2. Administration → Access Management → Teams: a team `sbom-upload` with the
   `BOM_UPLOAD`, `PROJECT_CREATION_UPLOAD`, `VIEW_PORTFOLIO`,
   `VULNERABILITY_ANALYSIS_UPDATE` and `PORTFOLIO_MANAGEMENT_UPDATE`
   permissions, and an API key on
   it. `make bao-secrets` in the platform repository writes it to
   `kv/dependency-track/sbom-upload`; the job picks it up at its next run,
   or sooner:

    ```bash
    kubectl -n dependency-track create job --from=cronjob/sbom-upload sbom-upload-now
    kubectl -n dependency-track logs job/sbom-upload-now
    ```

3. Administration → Vulnerability Sources: OSV is off by default. Enable it
   with the `Debian`, `Alpine`, `Go`, `npm`, `PyPI`, `Maven`, `NuGet`,
   `crates.io` and `RubyGems` ecosystems; NVD and EPSS are on already.
   GitHub Advisories needs a token.

    !!! warning "Without OSV the portfolio has components and no findings"
        NVD describes what a vulnerability affects as a CPE, and the internal
        analyzer skips any component without one. Trivy's SBOMs are mostly
        operating-system and language packages, which carry a PURL and no
        CPE, so NVD alone matches almost nothing here however many hundred
        thousand advisories it has mirrored. OSV and GitHub Advisories are
        the ones that match on PURL. A full portfolio reporting zero
        vulnerabilities is this, not a clean estate.

    OSV mirrors at 03:00 and NVD at 04:00, so findings appear the morning
    after the source is switched on, not the minute it is.
4. Administration → Configuration → Maintenance: enable inactive project
   deletion, by versions. Without it a [retired](#retired-projects) project
   stays forever.
5. Administration → Repositories: disable the repositories the
   [egress policy](#network-policy) does not allow, or every analysis logs a
   failed lookup for them.

### Reading it

The portfolio is one project per image; the `namespace:` tags say where it
runs. A vulnerability's Affected Projects view is the cross-image question
Trivy's per-container reports cannot answer directly. The same objects are
in the API:

```bash
# Every project and its version, newest upload first
curl -s -H "X-Api-Key: $KEY" "https://sbom.k8s.wlkr.ch/api/v1/project?sortName=lastBomImport&sortOrder=desc" \
  | jq -r '.[] | [.name, .version, .lastBomImport] | @tsv'

# Findings for one project
curl -s -H "X-Api-Key: $KEY" "https://sbom.k8s.wlkr.ch/api/v1/finding/project/<uuid>" \
  | jq -r '.[] | [.vulnerability.severity, .vulnerability.vulnId, .component.purl] | @tsv'
```

## Health check

```bash
kubectl -n dependency-track get pods,cronjob
kubectl -n dependency-track get cluster dependency-track-db
curl -s https://sbom.k8s.wlkr.ch/api/version | jq .version
```

The database should report `Cluster in healthy state`, the version endpoint
answers without a login, and the last `sbom-upload` job should have
succeeded with a line like `66 images, 0 failed, 0 reports skipped, 110 from
superseded revisions`. In the UI, the Dashboard's
portfolio count should match that number.

## Pitfalls

!!! warning "The KEK is the database"
    Every secret Dependency-Track stores, feed tokens and notification
    credentials among them, is encrypted with the key in
    `kv/dependency-track/config`. Deleting that path makes the `PushSecret`
    write a new key and leaves the database unreadable in those places. A
    restore of the database is only a restore together with the key.

- **A login that fails on `iss`** is a mismatch between the issuer in
  `application.yaml` and Authentik's, usually the trailing slash. Both
  Deployments carry the value; change it in one place.
- **A first login that lands nowhere** is a user with no team. Provisioning
  creates the account; the group mapping in [First login](#first-login) is
  what grants it anything.
- **A job that reports `no API key yet`** is the [first-login](#first-login)
  step not done, or the `ExternalSecret` not refreshed since it was; the
  Secret carries a `data-hash` annotation that moves when the value does.
- **A sync that stops at the database** with `could not get secret data from
  provider` is `kv/dependency-track/sbom-upload` missing entirely. Run
  `make bao-secrets` in the platform repository, which writes the path empty
  when there is no key yet; an absent path fails the `ExternalSecret`, and a
  failed resource stops the wave it is in.
- **Old image versions pile up as projects** when inactive project
  deletion is off under Maintenance, or the team lacks the permission to
  [retire](#retired-projects) them. The job never deletes.
