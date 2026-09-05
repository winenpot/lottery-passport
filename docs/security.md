# Security

## Authentication boundaries

The application has two deliberately separate credential paths:

- **User authentication:** passwordless email challenge followed by a server-
  side session identified by an HttpOnly cookie.
- **Machine authentication:** the existing `X-API-Key` dependency is reserved
  for trusted server-to-server or administrative integrations. It is not the
  user authentication mechanism and is not applied to `/api/v1/me`.

An API key must remain in a frontend server or backend-for-frontend service. It
must never be embedded in browser JavaScript. `CORS_ORIGINS=*` is compatible
with machine-to-machine requests because those callers do not use browser
cookies. Browser clients using user sessions require explicit origins and
credentialed CORS.

## Passwordless flow

`POST /api/v1/auth/request` normalizes the identifier, creates the user if
needed, creates a short-lived challenge, and sends a six-digit code through the
configured email port. The response is intentionally generic so it does not
reveal whether an identifier already exists.

Only a salted SHA-256 representation of the code is stored. Challenges expire,
track failed attempts, and are consumed with a conditional database update so
two concurrent verification requests cannot both create sessions.

Successful verification creates a random session token. Only its SHA-256 hash
is stored. The plaintext token is sent only as an HttpOnly cookie. Sessions can
expire and be revoked by logout.

## Development and production

The development email adapter stores the last generated code in application
memory for test fixtures. It does not send email and does not log the code.
The `unconfigured` provider intentionally fails rather than pretending that
email delivery exists. Configure a real provider adapter before enabling public
passwordless login in a deployed environment.

Production traffic must use HTTPS. Session cookies are `Secure` outside the
development environment, `HttpOnly`, and `SameSite=Lax`.

The current rate limiter is process-local and suitable only for the single-
instance demo. A distributed deployment needs a shared limiter such as Redis.
Request logging excludes authentication codes, cookies, API keys, request
bodies, and exception messages.