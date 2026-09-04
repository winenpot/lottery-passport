# Deployment

## Local Docker

Start the API and PostgreSQL together:

```powershell
docker compose up --build
```

The API is available at `http://localhost:8000`. The API connects to the
database using the Docker service name `postgres`, not `localhost`.
This PostgreSQL service and its development-only credentials are local Compose
resources; they are not production infrastructure.

## CI

GitHub Actions starts PostgreSQL 16 as a service container, runs the Alembic
migrations against it, runs the integration and unit tests, checks Ruff,
formatting, mypy, and builds the Docker image. A missing or unreachable test
database fails the workflow; integration tests are not allowed to be skipped in
CI.

## Demo Render deployment

`render.yaml` defines a Docker web service and a separate Render PostgreSQL
resource. Render should be connected to the GitHub repository with Blueprint
deployment enabled. The service runs `.venv/bin/alembic upgrade head` as its
pre-deploy command and uses `/health` for health checks.

Render injects the managed database's connection URI into `DATABASE_URL`.
Production-like environments reject local hosts such as `localhost` and
`postgres`, so the Compose database cannot be used accidentally by the deployed
service. Credentials are supplied by the database provider through the URI;
they are not committed to this repository.

The Blueprint uses Render's Free PostgreSQL plan for demonstration and public
validation only. Free Postgres is temporary/demo-only storage and must not be
treated as durable production data. Before production use, select a durable
database plan and configure backups, retention, monitoring, and recovery
procedures.

## Future production topology

The intended production shape is:

```text
Caddy edge proxy -> campaign API container -> PostgreSQL
```

Caddy, TLS certificates, public DNS, and proxy routing are deliberately not
part of this repository. The application only handles HTTP and receives its
port and trusted forwarded-proxy addresses through environment variables.