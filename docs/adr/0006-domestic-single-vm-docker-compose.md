# ADR-0006: Domestic hosting on a single VM with Docker Compose

**Status:** Accepted (supersedes the Render demo deployment; `render.yaml` removed 2026-10-18, deploys per ADR-0011)
**Date:** 2026-10-07
**Deciders:** Backend developer; CEO (cost)

## Context

The original plan deployed a demo to Render (US). Players are in Iran. During the June 2025
disruption, international connectivity collapsed for days while the domestic network stayed
up; foreign platforms can also refuse Iranian users because of sanctions. Latency to foreign
regions is high. The team has no dedicated DevOps person.

## Decision

- Host staging and production on **Iranian VMs** (two separate VMs), each running Docker Compose with nginx, api, worker and postgres.
- Keep everything on the request path domestic: fonts, scripts, images, SMS providers, monitoring targets.
- Off-site backups go to a second location (another domestic provider's object storage; a copy abroad is optional and is not on the request path).
- ~~Keep `render.yaml` only as a historical demo artefact.~~ Removed 2026-10-18; the Render demo is retired.

## Options considered

### Option A: domestic VM + Compose (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low: one host, one Compose file, a deploy script |
| Cost | Low |
| Availability | Single host is a single point of failure; mitigated by fast restore and a warm second VM later |
| Team familiarity | Medium (Docker is new for the developer; Compose keeps it small) |

### Option B: foreign PaaS (Render, Fly, Cloud Run)

Rejected: reachability during disruptions, sanctions, latency.

### Option C: Kubernetes (domestic managed or self-run)

Rejected for the MVP: too much to learn and operate in 15 days for no load-driven reason.

## Trade-off analysis

A single VM can fail; a restore from the last backup onto a fresh VM must take under two hours
and is rehearsed. That is acceptable for a promotional game, and much simpler than clustering.

## Consequences

- Easier: one place to look; cheap; fast to rebuild.
- Harder: Docker Hub refuses Iranian IP addresses, so images are pulled through a domestic registry mirror or built elsewhere and transferred ([OPERATIONS.md](../OPERATIONS.md#getting-images-and-packages-onto-the-server)).
- Revisit: add a warm standby VM with streaming replication after launch if the CEO wants RTO under 30 minutes.

## Action items

1. [ ] Order staging (D1) and production (D8) VMs (B08, B23).
2. [ ] Production Compose file, nginx config, deploy and backup scripts (B12, B23, B24).
