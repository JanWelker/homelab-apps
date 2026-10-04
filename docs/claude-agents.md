---
description: "Long-running Claude Code agents on the cluster, one per session: an sshd and a tmux session on a volume, reached over TLS on the Gateway, with a deliberately small reach."
---

# Claude agents

Each session is a Claude Code instance that keeps running when the laptop is
closed: a pod with `sshd`, a tmux session and a volume, reached at
`<session>.ssh.wlkr.ch`. The same session is also driven from the Claude apps
through Remote Control. The image and the Helm chart are the user's own,
built in the `claude-agent` repository, which
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only)
allows for the same reason as the Flowscape image. This repository holds the
namespace, the two ServiceAccounts and one directory per session.

## At a glance

| | |
| --- | --- |
| Hostname | `<session>.ssh.wlkr.ch`, a passthrough `TLSRoute` on `apps-gateway` that the chart renders; external-dns publishes it |
| Authentication | SSH public keys only; no password, no root |
| Storage | One PVC per session: `$HOME`, the clone, the Claude login and the conversation history |
| Database | None |
| Secrets | `kv/claude-<session>/github` and `kv/claude-agents/argocd` in OpenBao |
| Files | [`claude-agents/`](https://github.com/JanWelker/homelab-apps/tree/main/claude-agents) for the namespace; one `claude-<session>/` per session, see [Sessions](#sessions) |

## Sessions

| Session | Repositories | Cluster access | Why it is its own session |
| --- | --- | --- | --- |
| [`homelab`](https://github.com/JanWelker/homelab-apps/tree/main/claude-homelab) | `homelab`, `homelab-apps`, `claude-agent`, `flowscape`, `knead-time`, `fest.wollbi.ch`, `advent.wollbi.ch`, `renovate-config` | read, Argo CD | Everything that runs on or ships to the cluster, so one agent sees both halves of a rollout |
| [`sitzplan`](https://github.com/JanWelker/homelab-apps/tree/main/claude-sitzplan) | `sitzplan.schlumpf.me` | none | Hosted outside the cluster; needs only npm besides GitHub |
| [`virgil`](https://github.com/JanWelker/homelab-apps/tree/main/claude-virgil) | `virgil` | none | An iOS app: the agent edits and opens pull requests, CI builds, because there is no Xcode on Linux |

## Configuration

| Setting | Why |
| --- | --- |
| `claude-agents/` is plain manifests; each session is a separate Application on the OCI chart | The namespace outlives any one session. Removing a session must not prune the namespace or the other sessions |
| Session Applications have a single source and no `directory.exclude` | `exclude` filters a Git directory source. An OCI chart has none, so there is nothing for `application.yaml` to be excluded from |
| The namespace enforces `restricted` | The image runs as uid 1000 with every capability dropped and a read-only root filesystem |
| `claude-reader` and `claude-writer` are created here with `automountServiceAccountToken: false` | The platform binds them to the read and write ClusterRoles. A pod gets a token only by setting `kubernetes.access`, which keeps the choice visible in the session's own file |
| `kubernetes.access: read` | The sessions investigate and open pull requests; the cluster changes through Git and ArgoCD, not through the agent |
| `argocd.enabled: true` | Lets the agent read and sync applications with the `claude` account's token instead of guessing from the Git side |
| `repos` set per session | Clones each repository once into `$HOME` and creates the GitHub token `ExternalSecret`; one token covers the list. Without repositories there is no clone, no token and no GitHub egress |
| `skills.repo: JanWelker/claude-skills` | The private repository behind the laptop's `~/.claude/skills`, cloned into the same place and pulled at every session start, so a session runs the same skills and can push changes to them |
| `extraEgressFQDNs` per session | A session reaches the package registries its own build needs, and no others |
| `targetRevision` is the only version | The chart's `appVersion` is the Claude Code version and the image tag defaults to it, so a Claude Code release is a chart release |
| TLS ends in a `socat` sidecar from the same image, with a per-session `Certificate` | Cilium's Gateway only passes `TLSRoute` traffic through, it cannot terminate it; sshd itself listens on loopback only |
| `resources`: 768Mi requested, 4Gi limit | An agent idles between prompts at a few hundred MiB; the chart's 2Gi request does not fit beside the rest of the workers. The limit leaves room for builds and subagents |
| `ssh.authorizedKeys` holds public keys | They are public data: the same lines as `github.com/JanWelker.keys` |

### Network policy

Every rule in
[`claude-agents/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/claude-agents/networkpolicy.yaml),
and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).
The names an agent may reach live in each session's own policy, rendered by
the chart from its values (`extraEgressFQDNs` adds to them).

| Rule | Why |
| --- | --- |
| Ingress on 2222 from the `ingress` entity | The Gateway passes the TLS stream through by SNI to the pod's TLS sidecar, so the Gateway is the only way in |
| Ingress from `host` | The kubelet's probes, which come from the pod's own node. The Gateway arrives as the `ingress` entity from any node, so `remote-node` is not needed |
| Ingress and egress within the namespace | Sessions share the namespace; the policy does not split them further |
| Default egress to the namespace only | A session reaches nothing else unless its own policy says so. Those names (the Claude API, GitHub when `repo` is set, the Argo CD server) are the agent's reach, so adding one is reviewed like a firewall change |

## Usage

### SSH config

One block covers every session, because the hostname is the only thing that
differs:

```text
Host *.ssh.wlkr.ch
  User agent
  ProxyCommand openssl s_client -quiet -verify_return_error -servername %h -connect %h:443
```

`sshd` admits only the user `agent`. Then `ssh homelab.ssh.wlkr.ch` attaches to the tmux session `main`. With a
command, `ssh homelab.ssh.wlkr.ch <command>` runs it directly, so `scp` and
`rsync` work.

### First login

Once per session, after the first start:

1. `ssh <session>.ssh.wlkr.ch`.
2. Claude Code asks how to log in: pick **Claude account with subscription**
   and finish the browser flow.

The login lives on the volume and survives restarts. Remote Control is on for
every session through the image's managed settings; the session appears in
the Claude apps as `claude-<session>`.

### Secrets

None is generated: each comes from an account outside the cluster. In the
platform repository, `make claude-session-pat SESSION=<session>` writes a
session's token and `make bao-secrets` the shared Argo CD one.

| Path | Key | Read as |
| --- | --- | --- |
| `kv/claude-<session>/github` | `token` | `GH_TOKEN`: the fine-grained token for that session's repositories. Only when `repos` is set |
| `kv/claude-agents/argocd` | `token` | The Argo CD `claude` account's API token, from `argocd account generate-token --account claude`. Only when `argocd.enabled` |

### Creating the GitHub token

A fine-grained personal access token, one per session, so a leak costs that
session's repositories only:

1. GitHub → Settings → Developer settings → Fine-grained tokens → Generate.
   A session that gains a repository keeps its token: edit it and add the
   repository.
2. Resource owner `JanWelker`; **Only select repositories**, and pick the
   session's `repos` plus `claude-skills`.
3. Repository permissions:

    | Permission | Access | Why |
    | --- | --- | --- |
    | Contents | Read and write | Clone and push branches |
    | Pull requests | Read and write | Open and update pull requests |
    | Workflows | Read and write | A push that touches `.github/workflows/` is rejected without it |
    | Actions, Checks, Commit statuses | Read | `gh run` and `gh pr checks` |
    | Metadata | Read | Mandatory, added automatically |

4. Put the token into `kv/claude-<session>/github` (see above).

### Adding a session

The `claude-session` skill walks through these steps.

1. Copy a session directory, for example `claude-sitzplan/` to
   `claude-<session>/`.
2. In `application.yaml`, change `metadata.name`, `session`, `repos`, the
   access toggles and `extraEgressFQDNs`.
3. Create the token and write it to OpenBao before the merge, so the
   `ExternalSecret` resolves on the first sync.
4. Add the session to [Sessions](#sessions) and merge. It answers at
   `<session>.ssh.wlkr.ch` once the Application is Healthy; then do the
   [first login](#first-login).

### Removing a session

1. Delete `claude-<session>/` and its row in [Sessions](#sessions), and
   merge.
2. The ApplicationSet preserves resources on deletion, so remove them by
   hand: `kubectl -n claude-agents delete all,configmap,externalsecret,certificate,secret,tlsroute,ciliumnetworkpolicy,serviceaccount -l app.kubernetes.io/instance=claude-<session>`,
   then `secret/claude-<session>-tls`, which cert-manager creates without
   that label.
3. The volume is kept on purpose (`Prune=false`, `helm.sh/resource-policy:
   keep`). Delete `pvc/claude-<session>` once nothing on it is needed.
4. Remove the token: `make claude-session-pat SESSION=<session> DELETE=1` in
   the platform repository, and revoke it on GitHub.

Every session shares one `targetRevision` in practice: Renovate groups them
into one pull request.

### Sessions without a repository

Leave `repos` empty. The pod then has no clone, no GitHub token
and no GitHub egress, and the `kv/claude-<session>/github` path is not read.
Use it for a scratch session that only needs the Claude API.

### ACP from Zed

Set `acp.enabled: true` in the session's values. Zed then starts the agent
over the same SSH connection (`ssh <session>.ssh.wlkr.ch claude-code-acp`),
which works because a command bypasses tmux.

### Hosted side checklist

What lives on Anthropic's and GitHub's side, not in this repository:

- [ ] The Claude GitHub App is installed on all repositories the sessions
      touch.
- [ ] Auto-fix is enabled for pull requests the sessions open.
- [ ] Cloud environments exist for the repositories that need a hosted run.
- [ ] Routines run the sweeps that need no cluster access: Renovate pull
      requests and merge conflicts.

## Health check

```bash
kubectl -n claude-agents get pods,statefulsets
kubectl -n claude-agents get tlsroute
openssl s_client -quiet -servername homelab.ssh.wlkr.ch -connect homelab.ssh.wlkr.ch:443 </dev/null 2>&1 | head -1
```

The last command prints the SSH banner (`SSH-2.0-OpenSSH_...`) when the whole
path works: DNS, certificate, Gateway, policy and `sshd`.

## Pitfalls

- **An update restarts the pod and ends the running turn.** A new chart
  version is a new pod. The conversation survives on the volume: the start
  script runs `claude --continue`, which resumes it, but a turn in flight is
  lost. Merge version bumps between turns.
- **Remote Control needs a full subscription login.** `claude auth login`
  works; a `setup-token` or an API key does not, and the session then shows
  up nowhere in the apps.
- **The network policies are not enforced yet.** While the platform runs with
  `policyAuditMode`, Cilium logs what it would drop and drops nothing. Treat
  the egress list as intent until that is switched off; see
  [Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).
