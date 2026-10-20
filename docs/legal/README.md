# Legal texts (terms of use + privacy)

Since LG1' (2026-10-20) the text lives in the database, table `legal_documents`, one row
per version, and is edited in the admin panel: **/admin → Terms & privacy**. The public
page is `https://<host>/legal/<version>`, rendered by the API (`app/api/legal.py`); the
privacy section is the same page with `#privacy`.

`<version>` is the exact `TERMS_VERSION` value a server runs with (`app/core/config.py`,
1-20 letters, digits, `-` or `_`; we use the date). Players accept a version through
`PATCH /api/v1/me` `accept_terms_version`; the database keeps the version and the time
(`users.terms_version`, `users.terms_accepted_at`).

Rules:

- A version any player has accepted is frozen: a database trigger (migration 0020)
  refuses UPDATE and DELETE, and the panel says why. Change the text = create a new
  version in the panel, then move the server's `TERMS_VERSION`, `TERMS_URL` and
  `PRIVACY_URL` to it. Old versions stay, so we can always show exactly what a player
  agreed to; the audit log keeps every panel edit made before acceptance.
- A version nobody has accepted yet (a draft) may be edited in the panel freely.
- Company details in the text are public record and are shown to every player; they
  belong in the text, not in `.env`. Only the pointers are per server.
- Internal notes about the text (legal risk, negotiation) never go in this directory or
  in the panel: the repository and the page are public.
- Formatting the page understands: `#`/`##` headings (a trailing `{#id}` sets the
  anchor, e.g. `{#privacy}`), paragraphs separated by a blank line, `-` list items
  (indented lines continue the item) and `---` rules. Anything else shows as plain text.

`terms-2026-10-20.fa.md` here is the first draft as written; migration 0020 seeded it into
the database (plus the `{#terms}`/`{#privacy}` anchors). Edit it in the panel from now
on, not here: nothing reads this file and it will not be updated.

Status: version 2026-10-20 awaits business approval (LG2). Still open per server:
`TERMS_VERSION=2026-10-20`, `TERMS_URL=https://<host>/legal/2026-10-20`,
`PRIVACY_URL=https://<host>/legal/2026-10-20#privacy`.
