# Architecture

Phase 1 is a modular monolith using Hexagonal Architecture. The backend exposes
HTTP through FastAPI, while application services depend on explicit ports in
`app/application`. The PostgreSQL adapter in
`app/infrastructure/postgres` implements those ports. `create_app` is the
composition root where adapters are wired into application services.

Domain and application code must remain independent of FastAPI, SQLAlchemy,
PostgreSQL, OpenAI, email providers, and external infrastructure. Adapters may
depend on those technologies; the dependency direction points inward through
protocols. SQLAlchemy uses async PostgreSQL access; Alembic is an explicit
deployment step rather than an application-startup side effect.

Phase 2 adds a framework-free identity and authentication application service.
It depends on ports for users, challenges, sessions, clocks, code generation,
and email delivery. PostgreSQL repositories and the development email adapter
implement those ports under `app/infrastructure`; FastAPI only maps HTTP and
cookies to the service.

The intended deployment boundary is:

```text
Caddy or another edge proxy
        |
Dockerized campaign API
        |
PostgreSQL
```

The edge proxy is outside this repository. The API speaks HTTP, listens on
`0.0.0.0:$PORT`, and does not terminate TLS or configure DNS. Forwarded headers
are enabled by the container command only for the IPs configured by
`FORWARDED_ALLOW_IPS`; arbitrary proxy headers are not implicitly trusted.

## Passport terminology

The product domain will contain seven campaign/product passports:

- Paris
- Berlin
- Pattaya
- Mexico
- Madrid
- Tokyo
- Moscow

A user may have progress in multiple passports. Future modeling should use a
`UserPassport[]` relationship or equivalent campaign-scoped structure, not one
generic `User.passport_points` field. Passport scoring and prize logic are
intentionally not implemented in Phase 2.

## Authentication terminology

User authentication is passwordless and session-based. The future campaign
domain must not use a single generic API key or a singular passport score as a
user identity or progress model. Machine-to-machine API keys remain a separate
integration concern.