# Legal texts (terms of use + privacy)

One file per version: `terms-<version>.fa.md`, where `<version>` is the exact
`TERMS_VERSION` value the servers run with (`app/core/config.py`, a date,
max 20 characters). Players accept a version through
`PATCH /api/v1/me` `accept_terms_version`; the database keeps the version and
the time (`users.terms_version`, `users.terms_accepted_at`).

Rules:

- Never edit a version after it is published and a player may have accepted it.
  Change the text = new file with a new date + new `TERMS_VERSION` on the servers.
  Old files stay, so we can always show exactly what a player agreed to; git
  history is the audit trail.
- A version nobody has accepted yet (a draft) may still be edited in place.
- Company details in the text are public record and are shown to every player;
  they belong here, not in `.env`. Only the pointers are per server:
  `TERMS_VERSION`, `TERMS_URL`, `PRIVACY_URL`.
- Internal notes about the text (legal risk, negotiation) never go in this
  directory: the repository is public.

Status: `terms-2026-10-20.fa.md` is the first draft, awaiting business approval.
Serving (LG1) is built: nginx (`deploy/nginx/snippets/app.conf`) serves
`https://<host>/legal/<version>` as `text/plain; charset=utf-8` straight from
this directory (`deploy/compose.yml` mounts this directory read-only into the
nginx container at `/etc/nginx/legal`), cached forever since a version is
immutable once published. One file covers both sections, so `TERMS_URL` and
`PRIVACY_URL` are the SAME url -- plain text has no anchors to scroll to a
section, so a `#privacy` fragment would be a dead decoration, not a real
jump; if that distinction matters later, split privacy into its own
versioned file instead of faking an anchor. Still open: setting
`TERMS_VERSION`/`TERMS_URL`/`PRIVACY_URL` on a server's `.env` (per-server,
only via an approved release) and Mehdi's approval of the text (LG2).
