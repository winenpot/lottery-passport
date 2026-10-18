# ADR 0011: Pull-based deploys of one CI-built image from GHCR

Date: 2026-10-18. Status: accepted. Extends ADR 0006 (domestic single VM per environment).

## Context

Render (the demo host) is retired. Staging moves to atpg, a shared app server in Iran
behind ArvanCloud (`staging.torshx.com` -> atpg:8098); production is a new VM in Iran
(`play.torshx.com`). The owner wants every master commit that passes CI to reach staging
without manual steps, and production to follow on an approved release. Constraints:

- The repository is public. GitHub warns against self-hosted runners on public repositories
  (a pull request could run code on the runner's machine).
- atpg hosts ~25 other services. A deploy key for it in GitHub secrets is a risk to all of them.
- Inbound traffic from abroad to Iranian data centres is filtered unpredictably; outbound to
  `github.com` and `ghcr.io` works today (checked from atpg, 2026-10-18).
- Docker Hub refuses Iranian IPs (a domestic mirror serves base images); PyPI is slow.

## Decision

1. CI builds **one image per master commit** and pushes it to GHCR
   (`ghcr.io/winenpot/lottery-passport:sha-<commit>`, label
   `org.opencontainers.image.revision`, `GIT_COMMIT` baked in for `/health`). Servers never
   build. The package is public (the code is public; the image holds no secrets).
2. **Channel tags**: CI moves `:staging` after the quality job passes. A release tag
   `vYYYY.MM.DD-N` runs the Release workflow, which waits for approval in the GitHub
   environment `production` and then points `:production` at the same image (no rebuild).
3. **Each server pulls**: `lp-deploy.timer` runs `deploy/deploy.sh` every minute. When the
   channel tag points at a new digest, it checks out that commit's `deploy/` files (public
   https clone, no key), runs migrations with the new image while the old API serves,
   switches, reloads nginx after `nginx -t`, and waits for `/ready`. On failure it switches
   back to the previous digest and records the bad one so it is not retried.
4. CI closes the loop by polling the public `/health` until `commit` equals the pushed
   commit (`staging-verify`, `production-verify`).
5. One nginx configuration for both environments (shared locations, a small file per
   environment), so staging rehearses production.

## Consequences

- GitHub holds no server credentials; nothing inbound from abroad is needed; a pull request
  cannot reach a server.
- Up to one minute of extra latency per deploy, and the GitHub UI shows a deploy result only
  through the verify jobs.
- A failed release costs up to ~90 s of downtime before the automatic rollback (the old
  container is replaced before `/ready` is known). Acceptable: production only runs images
  that already ran on staging.
- Rolling back code relies on additive migrations during the campaign (unchanged rule).
- If `ghcr.io` becomes unreachable from Iran, deploys stop (running services are unaffected).
  Fallback: `docker save | ssh <server> docker load` and `deploy.sh <image>`.

## Options considered

- **SSH push from GitHub Actions**: simplest to read in the UI, but needs a key for a shared
  server in GitHub and inbound SSH from GitHub's runners abroad.
- **Self-hosted runner on atpg**: outbound only, but unsafe on a public repository.
- **Build on the server from git** (the previous `deploy.sh`): different bytes per
  environment, PyPI and Docker Hub on every deploy, slow on a shared machine.
- **Watchtower**: no migrations step, no rollback, no `/ready` gate.
