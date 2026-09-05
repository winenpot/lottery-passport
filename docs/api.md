# API

The Phase 2 API is versioned under `/api/v1`.

## Passwordless authentication

Request a challenge:

```http
POST /api/v1/auth/request
Content-Type: application/json

{"identifier":"user@example.com"}
```

The response is always generic:

```json
{"message":"If the identifier can be used, verification instructions have been sent."}
```

Verify the code:

```http
POST /api/v1/auth/verify
Content-Type: application/json

{"identifier":"user@example.com","code":"123456"}
```

Successful verification sets the `lottery_passport_session` HttpOnly cookie.
Clients should retain and send that cookie; they should not read it from
JavaScript.

Log out:

```http
POST /api/v1/auth/logout
```

## Current user

```http
GET /api/v1/me
PATCH /api/v1/me
Content-Type: application/json

{"display_name":"Example nickname"}
```

Both endpoints require the session cookie and return `401` when the session is
missing, expired, revoked, or the account is inactive.

The OpenAPI document represents the real session cookie as the `Session Cookie`
security scheme. Swagger's cookie authentication is browser-oriented; use the
real verification flow first, then call `/api/v1/me` with the resulting cookie.

## Machine-to-machine API keys

The separate API-key dependency uses the `X-API-Key` header and is intended for
future trusted integration/admin routes:

```http
X-API-Key: <server-side-secret>
```

It is not a replacement for user sessions. Never place the key in browser
JavaScript or query parameters. No business route currently requires it.