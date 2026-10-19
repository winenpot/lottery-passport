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
Serving it as a page (`/legal/terms-<version>`) is launch-plan task LG1.
