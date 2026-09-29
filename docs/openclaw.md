---
description: "OpenClaw on the cluster: a self-hosted AI assistant gateway whose whole state is one volume, behind the Authentik proxy outpost, with an egress policy that is the agent's reach."
---

# OpenClaw

[OpenClaw](https://openclaw.ai/) is a self-hosted assistant: a gateway process
that holds sessions, tools and channel connections, and sends the thinking out
to a model API. It keeps everything it knows on one volume and has no database.
Upstream publishes an image and a reference set of Kubernetes manifests but no
chart, so this is plain manifests shaped after that reference, per
[Conventions → Official upstream sources only](conventions.md#2-official-upstream-sources-only).

## At a glance

| | |
| --- | --- |
| URL | [claw.k8s.wlkr.ch](https://claw.k8s.wlkr.ch) |
| Authentication | Authentik proxy outpost, in front of the gateway's own shared-secret token |
| Storage | One PVC: the config file, the channel credentials, the workspace and the session history |
| Database | None |
| Secrets | `kv/openclaw/config` in OpenBao |
| Files | [`openclaw/`](https://github.com/JanWelker/homelab-apps/tree/main/openclaw) |

## Configuration

| Setting | Why |
| --- | --- |
| Plain manifests, no chart | Upstream publishes none. The charts that exist are third-party repackagings of the same image |
| The namespace enforces `restricted` | The image runs as uid 1000, needs no capability, and with `/tmp` as an `emptyDir` its root filesystem is read-only |
| One volume, mounted twice by `subPath` | The gateway's state and its workspace are separate directories that must both survive a restart; one claim is one thing to back up and one thing to restore |
| The config file is seeded, not mounted | OpenBao would not help here: the gateway **rewrites this file itself** as channels are added. A mounted ConfigMap is read-only and would break the first change made in the UI, so the init container copies it only where there is nothing yet |
| `OPENCLAW_GATEWAY_BIND: lan` | The image binds to loopback by default, which works with `kubectl port-forward` and leaves a Service talking to nothing. See [Pitfalls](#pitfalls) |
| `OPENCLAW_GATEWAY_TOKEN` from OpenBao | The gateway's own shared secret, behind the outpost. Generated in the cluster it would change on every rebuild and lock out anything already paired |
| `update.checkOnStart: false` | The one thing OpenClaw phones home for. The egress policy would drop it anyway; switching it off keeps the drop log about real things |
| `OPENCLAW_SKIP_ONBOARDING` | The interactive onboarding cannot run in a pod that nobody is attached to; the seeded config is what it would have written |
| `HTTPRoute` targets `authentik-server`, not the app | The control UI drives an agent that can run tools. The outpost authenticates before the request reaches the gateway's own token, so the token is the second layer rather than the only one. The cross-namespace `backendRef` works only because the platform's `referencegrant.yaml` names this namespace; pointing the route at the Service removes the outer layer, so it deserves a second look in review |

### Network policy

Every rule in
[`openclaw/networkpolicy.yaml`](https://github.com/JanWelker/homelab-apps/blob/main/openclaw/networkpolicy.yaml),
and why it is there. The shape is
[Conventions → Ship a `CiliumNetworkPolicy`](conventions.md#5-ship-a-ciliumnetworkpolicy);
rollout and debugging are in
[Security Policies](https://homelab.wlkr.ch/platform/security-policies/#network-policies).

This is the one policy in this repository that is a containment boundary
rather than hygiene. Everywhere else the egress list describes what the
application happens to need; here it decides what an agent that can run tools
is able to reach.

| Rule | Why |
| --- | --- |
| Ingress on 18789 from the Authentik server pods only, with an L7 `http` rule | The outpost is the only path in. No `fromEntities: ingress`, so a request straight from the Gateway cannot skip the login |
| Egress to `api.anthropic.com` only | The model the agent thinks with. Every channel, tool and provider added later needs its name here too, which is what keeps that a deliberate change |
| No `kube-apiserver`, no `automountServiceAccountToken` | The pod holds no token and cannot talk to Kubernetes. An assistant that can read the cluster is a different application with a different review |
| No egress to other namespaces | The default-egress rule allows the `openclaw` namespace and nothing else; there is nothing else in it |

## Usage

### First login

1. Open [claw.k8s.wlkr.ch](https://claw.k8s.wlkr.ch) and sign in through
   Authentik.
2. The control UI asks for the gateway token; it is in OpenBao:

    ```bash
    kubectl -n openbao exec openbao-0 -- bao kv get -mount=kv \
      -field=gateway-token openclaw/config
    ```

### Adding a channel or a tool

Two steps, in this order, and the first is a pull request:

1. Add the hostname to the `openclaw` egress policy and merge it.
2. Configure the channel in the control UI.

Doing it the other way round produces a connection that hangs rather than one
that fails, which reads as a wrong credential.

### Secrets

`kv/openclaw/config` holds two values, written by `make bao-secrets` in the
platform repository, both at once because a `bao kv put` replaces a path
wholesale.

| Key | Read as |
| --- | --- |
| `gateway-token` | `OPENCLAW_GATEWAY_TOKEN`: the control UI's shared secret |
| `anthropic-api-key` | `ANTHROPIC_API_KEY`: the model the agent thinks with, the one value here that is typed in rather than generated |

Everything else OpenClaw holds — channel credentials, tool tokens — it stores
itself, on the volume. Those are not in OpenBao and are not in Git; the volume
is the only copy, and Velero's nightly snapshot the only backup.

## Health check

```bash
kubectl -n openclaw get pods
kubectl -n openclaw exec deploy/openclaw -- wget -qO- localhost:18789/readyz
```

`/readyz` reports the channel status as JSON; `/healthz` and `/startupz` are
the liveness and admission halves of the same contract. All three answer
without a token, which is what lets the kubelet use them.

## Pitfalls

!!! warning "The egress list is the containment"
    OpenClaw runs tools on behalf of a model. The network policy is what decides how far that reaches, and it is one name. Treat a pull request that adds to it the way you would treat one that widens a firewall, not the way you would treat a dependency bump.

- **A gateway bound to loopback looks like a crash loop.** The Service
  connects to nothing, the readiness probe fails from the kubelet's address,
  and the pod restarts. Check `OPENCLAW_GATEWAY_BIND` and the `gateway.bind`
  value in the seeded config before anything else.
- **The seed is applied once.** Changing `configmap.yaml` after the first
  start changes nothing: the init container only copies where the file is
  missing. Edit the live file with `kubectl exec`, or delete it and let the
  pod restart.
- **The volume is the only copy.** No database, no OpenBao path for what the
  gateway stores itself. Deleting the claim deletes every channel pairing.
