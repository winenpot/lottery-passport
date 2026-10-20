# ADR 0012: Pull-based auto-deploy of the frontend on staging only

Date: 2026-10-20. Status: accepted. Extends ADR 0011 to Arman's separate frontend
repository (`Arman13m99/TorshX_2`, private).

## Context

Publishing the frontend to staging was a manual loop every time Arman pushed to main:
download the CI artifact by hand, check its CI run and SHA256, SSH in, run
`publish_web.sh`. The backend already auto-deploys to staging on every green master
push (ADR 0011); the owner asked whether the same could notify/pull for the frontend.

Constraints:

- `TorshX_2` is a separate, private GitHub repository we do not own. There is no
  webhook endpoint on our servers to receive a push notification from it, and ADR 0011
  deliberately avoided taking inbound requests from GitHub.
- Reading its CI results needs a credential. A personal, broadly-scoped `gh` login
  (`repo`, `workflow` across every repo the owner can see) must never be copied onto a
  shared server; atpg hosts ~25 unrelated services.
- Production (`play.torshx.com`) already has an explicit human-approval gate for the
  backend (a `v*` tag + a required GitHub reviewer); the frontend has had no such gate
  at all, and the owner wants to keep a manual step for it on production (2026-10-20).

## Decision

1. **Same pull philosophy, adapted**: `lp-frontend-deploy.timer` runs
   `deploy/deploy_frontend.sh` every minute, **staging only**. It asks the GitHub API for
   the newest successful "Frontend CI" run on `TorshX_2`'s `main` (push event), downloads
   that run's `frontend-normal` artifact, and hands the zip to the existing
   `publish_web.sh` — the same verification (`metadata.json` `mode=api`, `index.html`,
   `assets/`) a manual publish already does.
2. **A narrow, purpose-made credential**: `FRONTEND_GH_TOKEN` is a fine-grained PAT
   scoped to only `TorshX_2`, permissions `Actions: read` + `Contents: read` (metadata
   read is implied). Created by Arman or the owner as a collaborator on that repo, never
   the owner's broad personal token. It lives only in staging's `.env` (mode 600);
   empty = the timer ticks and does nothing.
3. **Production stays manual** (owner's call): `lp-frontend-deploy.timer` is never
   installed on torshx. `publish_web.sh` is unchanged and is still how a verified build
   reaches `play.torshx.com`. Revisit if/when the frontend gets its own tagged-release
   gate to mirror the backend's.
4. State lives next to the backend agent's, under `<base>/state/frontend-*`, so a commit
   already published is never re-downloaded, and a failed one is not retried every
   minute (same shape as `deploy.sh`).

## Consequences

- Staging shows Arman's main within about a minute of his CI going green, no manual
  artifact download or hash check.
- The new token is the one new credential this introduces; its blast radius is read-only
  access to one repository's Actions results and artifacts, nothing else.
- A frontend-only outage (a bad build on staging) self-heals the moment Arman pushes a
  fix to main; there is no automatic rollback (unlike the backend's `deploy.sh`), because
  a bad static bundle is a direct symlink flip away from fixed (`web/current ->` the
  previous release) and does not need a database-aware rollback path.
- Production review for the frontend is still "the owner reads the diff and runs
  `publish_web.sh`", not a GitHub-reviewed gate; this is a deliberate smaller lift than
  the backend's, acceptable because the frontend carries no migrations and the rollback
  is just a symlink.

## Options considered

- **GitHub App installed on `TorshX_2`**: finer-grained and revocable without rotating a
  secret, but real setup work (manifest, installation, token exchange) for a single
  repository with one collaborator relationship; a PAT scoped to Actions+Contents read
  on just that repo gets the same blast radius with far less to build.
- **Inbound webhook from `TorshX_2`'s CI**: would need an endpoint reachable from
  GitHub's infrastructure abroad, the exact inbound exposure ADR 0011 ruled out for the
  backend.
- **Mirror the backend's tag + required-reviewer gate for production too**: rejected for
  now by the owner (2026-10-20); the frontend has no migrations to make a bad deploy
  risky in the same way, and a manual step is cheap while launch week is still active.

## Open question (2026-10-20, blocks going live)

A main-push run of "Frontend CI" does not carry a `frontend-normal` artifact at all — it
carries `release-plan.json` (a custom schema: `risk`, `scopes`, `reasons`,
`source.commit`/`source.tree`, `baseCommit`, `changedPaths`), which flags nearly any real
change `risk: critical` / `"...: fail closed"`. The buildable artifact lives only on the
originating PR's own run. `deploy_frontend.sh` is written, shellcheck-clean and dry-run
tested against the real API (it correctly finds the newest run and fails safe — logged,
not retried — when no `frontend-normal` artifact exists), but it does not yet know how to
resolve a main commit to the PR run that actually built it. Asked Arman (2026-10-20,
`.hermes/plans/2026-10-20_messages.md`) whether `release-plan.json` is his own consumer
contract. The timer is written but not yet enabled on atpg until this resolves.
