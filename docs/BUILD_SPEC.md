# Backend Engineering Specification: Campaign, Product Passport & Gamification Platform

You are acting as a senior backend engineer, software architect, security engineer, database designer, test engineer, and DevOps engineer.

We are building a backend from scratch for a public-facing campaign platform.

The platform allows users to sign up with minimal friction, maintain a lightweight profile, enter special codes printed on products, receive progress/score through a product "passport", participate in campaigns, and return later to see their progress and campaign status.

The system will initially be deployed as a demo on Render and maintained in GitHub with GitHub Actions.

The implementation must be production-minded even though the first deployment is a demo.

Do not build an unnecessarily complicated distributed system. Start as a modular monolith with strong internal boundaries so that individual components can later be extracted if required.

## 1. Core architectural decisions

Use:

* Python 3.13
* FastAPI
* Pydantic v2
* Pydantic Settings for configuration
* SQLAlchemy 2.x
* PostgreSQL
* Alembic for migrations
* pytest
* pytest-asyncio where appropriate
* Ruff for linting and formatting
* mypy where practical
* httpx for API integration tests
* Uvicorn for local/development serving
* Render for initial deployment
* GitHub Actions for CI

Prefer modern async-compatible PostgreSQL access.

Use a layered architecture:

API layer
→ application/service layer
→ domain/business logic
→ repository/data-access layer
→ PostgreSQL

Do not put business rules directly inside FastAPI route functions.

Do not allow database models to become the application's business logic.

Do not hardcode campaign scoring rules.

Do not hardcode assumptions about future campaigns.

## 2. Product concept

The platform contains:

1. Users
2. User profiles
3. Campaigns
4. Products
5. Product variants/SKUs where necessary
6. Product codes
7. Product code imports
8. Product code redemption events
9. User passport/progress
10. Score transactions
11. Scoring rules
12. Scoring rule versions
13. Campaign participation
14. Anti-abuse/risk signals
15. Administrative operations
16. Audit logs
17. Authentication/session information

The terminology used in code should remain generic.

Avoid naming the scoring system after a temporary marketing concept.

For example, prefer:

`score_ledger`

rather than:

`magic_points`

because the marketing name may change.

## 3. User experience assumptions

The public user journey should be deliberately lightweight.

A user should not need to complete a large profile just to participate.

The minimum profile should be approximately:

* id
* email or other chosen login identifier
* display name/nickname, optional
* created_at
* updated_at
* account status
* basic consent flags where legally required
* verification state

Do not collect date of birth, address, phone number, government ID, or other unnecessary personal information unless explicitly required later.

Design the schema so that optional profile data can be added later without restructuring authentication.

## 4. Authentication

Use passwordless authentication as the preferred initial approach.

Recommended flow:

1. User submits email.
2. Backend creates a short-lived login challenge.
3. A single-use token/code is generated.
4. Token expires.
5. Token is consumed atomically.
6. On successful verification, establish an authenticated session.

The design must prevent:

* token reuse
* token guessing
* unlimited token creation
* brute force verification
* enumeration of existing users
* excessive login attempts
* replay attacks

Never store authentication tokens in plaintext when a securely hashed representation can be stored instead.

Create an authentication abstraction so that future mechanisms such as OAuth/social login can be added without rewriting the user domain.

For the first demo, make the email provider configurable.

A local development implementation may log verification links/codes safely rather than sending real email.

## 5. Session strategy

Prefer secure server-side or signed authentication mechanisms appropriate for a browser-based frontend.

If cookies are used:

* Secure in production
* HttpOnly where appropriate
* SameSite configured deliberately
* short-lived access/session state
* explicit session revocation

Do not expose authentication secrets to frontend JavaScript unnecessarily.

Do not store secrets in the database or repository in plaintext.

Document the authentication threat model.

## 6. Campaign model

A campaign is a first-class object.

It should support:

* id
* internal name
* public name
* description
* status
* start_at
* end_at
* configuration
* created_at
* updated_at

Use an explicit campaign status model such as:

* draft
* scheduled
* active
* paused
* completed
* archived

Campaigns must not depend on a single global scoring formula.

Each campaign should be able to reference a scoring configuration/version.

A campaign may have multiple products.

A user may participate in multiple campaigns.

Do not assume there will only ever be one campaign.

## 7. Product model

Products should be modeled independently from campaigns.

At minimum:

* id
* product code/internal identifier
* name
* description
* status
* metadata
* created_at
* updated_at

Consider a separate ProductVariant/SKU model if the campaign may distinguish between package sizes, flavors, editions, or regions.

Do not bury SKU-specific behavior inside the Product model.

Campaign/product relationships should be explicit.

## 8. Product codes

A printed product code is an important security boundary.

Model codes so that they can be:

* imported in bulk
* associated with a product
* associated with a campaign when applicable
* activated/deactivated
* redeemed
* audited
* queried safely

A code must never be redeemable twice unless a campaign configuration explicitly allows repeated use.

The database must enforce uniqueness.

Do not rely exclusively on application-level duplicate checks.

Design redemption as an atomic transaction.

A redemption should produce an immutable event/record such as:

`redemption`

containing:

* id
* user_id
* product_id
* campaign_id
* product_code_id
* redeemed_at
* score result
* scoring rule version
* idempotency information
* risk/review state
* metadata necessary for auditing

## 9. Code import

Very soon we will receive a spreadsheet containing the special numbers/codes that already exist on products.

Design for CSV and XLSX import.

Create a dedicated import pipeline.

Example flow:

uploaded file
→ validation
→ normalization
→ preview
→ duplicate detection
→ dry run
→ commit
→ import summary

The importer should report:

* total rows
* valid rows
* invalid rows
* duplicate rows
* unknown products
* unknown campaigns
* imported rows
* skipped rows
* errors

Do not blindly insert spreadsheet contents.

Validate every row.

The import process should be idempotent where practical.

Do not load a huge spreadsheet completely into memory if a streaming/batched approach is feasible.

Create an import job model if asynchronous processing becomes necessary.

For the first demo, synchronous processing is acceptable for small files, but keep the architecture ready for background jobs.

## 10. Code normalization

Define a single canonical normalization pipeline for codes.

For example:

* trim whitespace
* normalize allowed character case
* reject unexpected characters
* normalize formatting only when explicitly configured

Do not silently change potentially meaningful characters.

Make normalization behavior testable.

Never log full redemption codes in normal application logs.

Where possible, store a secure representation/fingerprint for lookup and only store plaintext code material when operationally necessary.

## 11. Redemption behavior

The endpoint should conceptually be:

POST /campaigns/{campaign_id}/redemptions

The request should contain the user-entered product code and any required product context.

The backend must:

1. authenticate the user
2. validate campaign status
3. normalize the code
4. locate the code
5. validate campaign/product compatibility
6. ensure code has not already been redeemed
7. evaluate abuse/risk checks
8. evaluate the scoring configuration
9. create a redemption
10. create score ledger entries
11. update any derived passport state
12. commit the transaction atomically

If any required operation fails, the transaction must not leave partially applied score changes.

Use database constraints and transactions to defend against concurrent redemption attempts.

Two simultaneous requests using the same code must not both succeed.

## 12. Idempotency

The redemption API must support idempotent requests.

A client retry after a network timeout must not create duplicate points.

Implement an idempotency-key strategy for state-changing operations where appropriate.

Store enough information to safely return the previous result for a repeated request.

Test this explicitly.

## 13. Passport/progress model

The user should have a conceptual "passport".

The passport is not merely one mutable integer.

Use a ledger-oriented design.

For example:

`score_ledger_entries`

Each entry should contain:

* id
* user_id
* campaign_id
* source_type
* source_id
* points
* scoring_rule_version_id
* created_at
* metadata

The current total score can be derived or maintained as a denormalized value.

The ledger is the source of truth.

This makes future features possible:

* score corrections
* reversals
* bonus campaigns
* administrator adjustments
* product-specific bonuses
* auditing
* historical scoring changes

Never overwrite historical score events.

If a score must be reversed, create a compensating ledger event.

## 14. Scoring engine

This is one of the most important architectural requirements.

DO NOT hardcode scoring logic inside route handlers.

Create a dedicated scoring engine.

Conceptually:

ScoringContext
→ ScoringRule
→ ScoreResult

The scoring context may contain:

* campaign
* product
* product variant
* user participation state
* redemption count
* previous score
* campaign configuration
* product attributes
* optional imported winning-number information
* timestamp
* rule version

The scoring result should contain enough explanation to audit why the points were awarded.

For example:

* points_awarded
* rule_version
* reason/code
* metadata/explanation

## 15. Scoring configuration

Campaigns must reference versioned scoring configurations.

Avoid hardcoding:

`Product A = 10 points`
`Product B = 20 points`

Instead, store configurable rules.

Potentially support rule types such as:

* fixed points
* product multiplier
* first redemption bonus
* campaign milestone
* category bonus
* threshold bonus
* winning-number bonus

The exact rule types should be extensible.

Prefer a plugin/strategy pattern over a giant chain of `if/elif`.

Each scoring rule should be deterministic and unit-testable.

A scoring result must be reproducible from the original inputs and rule version.

## 16. Winning numbers

We will receive numbers that have already been drawn/published and printed or associated with products.

Do not assume the future format prematurely.

Design a generic concept such as:

`winning_number_sets`

and/or

`campaign_number_rules`

with the ability to import external data.

The system may eventually need to support:

* exact match
* partial match
* numeric ranges
* prefixes
* suffixes
* multiple winning-number sets
* campaign-specific matching
* product-specific matching
* date/time windows

Do not encode one specific matching algorithm into the database schema.

The matching logic must be a service.

Imported number datasets must be versioned and auditable.

## 17. Anti-abuse

This is a public promotion system, so assume hostile traffic.

Implement an anti-abuse foundation without making legitimate users solve unnecessary challenges.

Potential controls:

* rate limiting
* login attempt throttling
* redemption throttling
* IP-derived risk signals
* device/session risk signals where legally appropriate
* suspicious velocity detection
* repeated failed-code tracking
* account status
* temporary blocks
* admin review state

Do not rely on IP address alone.

Avoid collecting more tracking data than necessary.

Design anti-abuse as a separate service/module.

The user-facing API should not reveal whether a code belongs to another person's account or expose sensitive internal validation details.

Consider CAPTCHA/Turnstile as an optional configurable layer for suspicious traffic rather than forcing every normal user through it.

## 18. Abuse scoring

Create a risk evaluation abstraction.

Example:

RiskContext
→ RiskEngine
→ RiskDecision

RiskDecision could contain:

* allow
* challenge
* review
* deny

Possible signals:

* too many attempts per minute
* too many failed attempts
* excessive redemptions
* unusual account velocity
* repeated code patterns
* known abusive IP/network
* suspicious account creation pattern

Keep this configurable.

Do not create an unmaintainable collection of magic numbers.

## 19. Database design principles

Use UUIDs or another robust identifier strategy.

Use UTC timestamps.

Use PostgreSQL constraints aggressively.

Include:

* unique constraints
* foreign keys
* check constraints where useful
* indexes for actual query paths

Index likely high-volume access paths, especially:

* user lookup
* campaign lookup
* code lookup
* redemption lookup
* score ledger lookup
* authentication challenge lookup

Avoid blindly indexing every column.

Use database transactions for all multi-step state changes.

## 20. Soft deletion

Do not automatically introduce soft deletion everywhere.

Only use it where business or audit requirements justify it.

Immutable history should be preserved where necessary.

## 21. Audit logging

Create an audit log for sensitive administrative and state-changing actions.

Potential audit events:

* campaign created/changed
* scoring configuration changed
* product changed
* code imported
* code redeemed
* score adjusted
* user blocked
* user unblocked
* authentication/security event

Audit events should contain:

* actor
* action
* entity
* entity id
* timestamp
* relevant metadata

Do not store passwords, tokens, full authentication secrets, or sensitive credentials in audit logs.

## 22. API structure

Use versioned APIs.

Example:

/api/v1/auth/...
/api/v1/users/...
/api/v1/campaigns/...
/api/v1/products/...
/api/v1/redemptions/...
/api/v1/passport/...
/api/v1/admin/...

Keep public and administrative APIs logically separated.

Use dependency injection for:

* authenticated user
* database session
* configuration
* service objects

Use Pydantic request/response schemas rather than exposing SQLAlchemy models directly.

## 23. Error handling

Define stable application error codes.

Do not return raw Python exceptions.

Example categories:

* AUTH_REQUIRED
* AUTH_INVALID
* RATE_LIMITED
* CAMPAIGN_NOT_ACTIVE
* CODE_INVALID
* CODE_ALREADY_REDEEMED
* CODE_NOT_ELIGIBLE
* REDEMPTION_BLOCKED
* VALIDATION_ERROR
* INTERNAL_ERROR

Error responses should be predictable for frontend developers.

Do not leak whether a sensitive identifier exists when that would facilitate enumeration.

## 24. Observability

Implement structured logging.

Each request should have a request/correlation ID.

Log:

* request ID
* route
* status code
* latency
* relevant internal identifiers

Do not log:

* authentication tokens
* session secrets
* passwords
* raw private credentials
* complete redemption codes

Add:

GET /health

and preferably:

GET /ready

where useful.

Health endpoints must not leak database credentials or implementation details.

## 25. Configuration

Use environment variables.

Create explicit settings such as:

DATABASE_URL
ENVIRONMENT
SECRET_KEY
AUTH_TOKEN_TTL
RATE_LIMIT_SETTINGS
CORS_ORIGINS
OPENAI_API_KEY
LOG_LEVEL

Do not commit secrets.

Provide:

`.env.example`

with safe placeholder values.

Make configuration typed and validated at startup.

## 26. Frontend assumptions

The frontend may be a separate application/server.

The backend remains the source of truth.

Client-side calculations may be used only for display/UX.

Never trust the frontend for:

* score totals
* campaign eligibility
* code validity
* redemption state
* identity
* administrative permissions

CORS must be explicitly configured.

If frontend and backend are served from the same origin through a reverse proxy, prefer that configuration where practical because it simplifies browser security.

## 27. Admin capabilities

The first version should have an internal administrative API, even if there is no polished admin UI.

Admin operations should include:

* create/update campaign
* activate/pause campaign
* create/update products
* import product codes
* inspect code status
* inspect redemptions
* inspect users
* inspect score ledger
* adjust/reverse score with audit trail
* inspect risk events

Administrative endpoints must use explicit authorization.

Do not assume that being authenticated means being an administrator.

## 28. Security boundaries

Apply:

* secure passwordless authentication
* authorization checks
* rate limiting
* request validation
* database constraints
* transaction isolation appropriate to redemption
* idempotency
* security headers where relevant
* CORS restrictions
* secret management
* dependency updates

Do not invent cryptographic algorithms.

Use established libraries.

Keep the threat model documented in `docs/security.md`.

## 29. Project layout

Use a structure similar to:

app/
main.py
core/
config.py
security.py
logging.py
errors.py
api/
deps.py
v1/
router.py
auth.py
users.py
campaigns.py
products.py
redemptions.py
passport.py
admin.py
db/
base.py
session.py
models/
schemas/
repositories/
services/
auth.py
campaign.py
redemption.py
scoring.py
risk.py
import_service.py
passport.py
domain/
scoring/
risk/
workers/
integrations/
email.py
openai.py
utils/

alembic/
tests/
unit/
integration/
api/
security/
fixtures/

docs/
architecture.md
security.md
scoring.md
deployment.md
api.md
operations.md

.github/
workflows/
ci.yml

Do not rigidly follow this layout if there is a cleaner structure, but preserve the separation of concerns.

## 30. Testing strategy

Create meaningful tests, not superficial tests.

Unit tests:

* code normalization
* scoring rules
* score calculation
* risk decisions
* campaign eligibility
* configuration validation

Integration tests:

* database repositories
* transactions
* unique constraints
* redemption flow
* idempotency
* concurrent redemption behavior

API tests:

* authentication
* campaign endpoints
* redemption endpoint
* passport endpoint
* authorization
* validation
* error responses
* rate limiting behavior

Security tests:

* token replay
* code replay
* enumeration resistance
* privilege escalation
* duplicate redemption
* race conditions

Import tests:

* valid CSV
* invalid CSV
* duplicate codes
* malformed rows
* missing products
* dry-run mode
* partial import failure
* repeated import

Use factories/fixtures for test data.

Avoid tests that depend on production data.

## 31. Concurrency testing

This is mandatory for redemption.

Write a test that attempts to redeem the same code concurrently.

Exactly one request should successfully perform the redemption.

All other attempts must receive the appropriate response without duplicate score ledger entries.

Do not merely check this in Python application code.

The database must participate in the guarantee.

## 32. Migration discipline

Every database schema change must use Alembic migrations.

Never ask developers to manually edit production tables.

Migrations should be:

* deterministic
* reviewed
* reversible when practical
* tested against the current schema

Do not automatically run destructive migrations during application startup.

For deployment, use a deliberate migration step.

## 33. CI

Create GitHub Actions CI that runs on pull requests and pushes to the main branch.

It should:

1. check out the repository
2. install the supported Python version
3. install dependencies
4. run Ruff linting
5. run Ruff formatting checks
6. run mypy where configured
7. run unit/integration tests
8. produce test/coverage output

Use the current GitHub Actions Python guidance and keep action versions current rather than blindly copying obsolete examples. GitHub's current documentation explicitly covers Python setup, pytest/coverage, and Ruff checks.

CI should fail on:

* lint errors
* formatting errors
* type errors where enabled
* failing tests

Do not hide failures using `continue-on-error`.

## 34. Dependency management

Use `pyproject.toml`.

Keep dependency versions controlled.

Separate:

* runtime dependencies
* development/test dependencies

Prefer a lockfile or reproducible dependency installation strategy.

Do not automatically upgrade all dependencies whenever CI runs.

## 35. Git strategy

Use:

main

for stable code.

Feature branches:

feature/<name>

Bug fixes:

fix/<name>

Keep commits focused.

Examples:

feat: add campaign model
feat: implement redemption service
test: cover duplicate redemption
fix: prevent token replay
chore: configure ruff
ci: add postgres integration tests

Do not make enormous commits containing unrelated generated files.

Do not commit:

* `.env`
* secrets
* database dumps
* local virtual environments
* coverage artifacts
* IDE-specific private files

Create a useful `.gitignore`.

## 36. Pull request discipline

Every feature should include:

* implementation
* tests
* migration if needed
* documentation update if behavior changed

The PR description should explain:

* what changed
* why
* database impact
* security impact
* testing performed

## 37. Render deployment

Prepare the project for Render.

Initial target:

FastAPI Web Service
+
Render PostgreSQL

Render currently supports FastAPI deployment with a Python build command and a Uvicorn start command, and managed PostgreSQL is available as a native service.

Create a `render.yaml` where practical so deployment configuration is version controlled.

Use environment variables for secrets and database connection information.

Implement a health endpoint.

Do not use development reload mode in production.

Keep production worker configuration configurable rather than hardcoded.

## 38. Database migration deployment

Provide a documented deployment sequence such as:

install dependencies
→ run Alembic migrations
→ start FastAPI

Do not perform destructive schema changes automatically.

Make migration failures visible.

## 39. Docker

Do not require Docker for local development unless it provides a clear advantage.

However, prepare a Dockerfile eventually or include one if it simplifies Render parity.

The architecture should remain container-compatible.

## 40. OpenAI integration

OpenAI is optional and must not become a dependency of the core campaign/redemption path unless a real business requirement exists.

If OpenAI functionality is introduced later, isolate it behind:

`integrations/openai.py`

and a service abstraction.

Never put OpenAI calls directly inside FastAPI route functions.

Never expose an OpenAI API key to the client.

Use environment-based configuration.

Use the official OpenAI SDK and current official OpenAI documentation rather than inventing API parameters. OpenAI's current documentation recommends the Responses API for current API use, and API keys must remain server-side rather than being exposed in client code.

If structured machine-readable model output is required, prefer schema-constrained structured outputs rather than asking the model to "please return JSON" and hoping for valid syntax.

If user-generated text or images are later processed by AI, consider the official moderation endpoint as a separate safety layer.

AI must never directly modify score, redemption, eligibility, authentication, or campaign state without deterministic server-side validation.

## 41. API documentation

Use FastAPI's OpenAPI generation.

Provide examples for important endpoints.

Document:

* authentication
* redemption
* passport
* campaigns
* imports
* administrative operations
* error codes

Do not expose internal admin endpoints as public functionality merely because they exist in OpenAPI.

## 42. Performance

Do not prematurely introduce Redis, queues, Kafka, microservices, or Kubernetes.

Start with:

FastAPI
+
PostgreSQL

Add Redis only if there is a real need for:

* distributed rate limiting
* cache
* short-lived coordination
* background task infrastructure

Add a job queue only when imports, notifications, or other operations become sufficiently expensive.

The architecture should make those additions possible later.

## 43. Caching

Never cache correctness-critical data in a way that can make redemptions inconsistent.

Caching may be used for:

* campaign display data
* product metadata
* public configuration
* read-heavy dashboards

Never allow cache state to become the authority for whether a code has already been redeemed.

## 44. Transactions

Treat redemption as a critical transaction.

A conceptual transaction is:

begin
→ lock/uniquely claim code
→ validate campaign
→ validate eligibility
→ evaluate risk
→ calculate score
→ create redemption event
→ create score ledger event
→ update derived passport state if used
→ commit

The design must clearly document which rows are locked or protected by uniqueness constraints.

## 45. Data consistency

The system should always preserve these invariants:

* one code cannot produce two successful redemptions
* one redemption cannot produce two score awards
* score ledger entries cannot be silently altered
* inactive campaigns cannot accept redemptions
* users cannot access another user's passport
* admins cannot accidentally bypass audit requirements
* imported codes cannot silently overwrite existing codes

Write tests around every invariant.

## 46. API examples

Create an initial endpoint catalog.

Example:

POST /api/v1/auth/request
POST /api/v1/auth/verify
POST /api/v1/auth/logout

GET /api/v1/me
PATCH /api/v1/me

GET /api/v1/campaigns
GET /api/v1/campaigns/{campaign_id}

POST /api/v1/campaigns/{campaign_id}/redemptions

GET /api/v1/me/passport
GET /api/v1/me/passport/history

Admin:

POST /api/v1/admin/campaigns
PATCH /api/v1/admin/campaigns/{campaign_id}
POST /api/v1/admin/products
POST /api/v1/admin/imports/codes
GET /api/v1/admin/imports/{import_id}
GET /api/v1/admin/redemptions
POST /api/v1/admin/score-adjustments

Treat this list as a starting point, not an immutable contract.

## 47. Response design

Use consistent response schemas.

Do not return ORM objects directly.

For example:

RedemptionResponse:

* redemption_id
* campaign_id
* product_id
* points_awarded
* passport_total
* status
* message
* rule_version

Do not expose sensitive internal information.

## 48. Admin score adjustments

Score corrections must never update a total blindly.

Create a compensating ledger entry.

The adjustment should record:

* administrator
* reason
* original context
* amount
* timestamp
* related entity

This makes the system auditable.

## 49. Documentation requirements

Create these documents:

`README.md`
`docs/architecture.md`
`docs/security.md`
`docs/scoring.md`
`docs/deployment.md`
`docs/imports.md`
`docs/operations.md`
`docs/api.md`

README should include:

* local setup
* environment variables
* database startup
* migrations
* test command
* lint command
* run command
* deployment overview

## 50. Development environment

Provide simple commands such as:

install dependencies
run migrations
start local API
run tests
run lint
run format
run type checks

Make them documented and consistent.

## 51. Local PostgreSQL

Prefer a simple local PostgreSQL setup.

Docker Compose may be provided as an optional development convenience.

Do not make the application depend on Docker in order to run unit tests.

Use a dedicated test database for integration tests.

## 52. Test database strategy

Integration tests must never connect to production.

Prefer a dedicated PostgreSQL test database.

Keep test setup isolated and repeatable.

Transactions/fixtures should clean up data between tests without making tests dependent on execution order.

## 53. Seed data

Create development/demo seed data:

* one active campaign
* a small number of products
* test scoring configuration
* sample product codes
* test admin user

Never use real credentials.

Clearly mark seed data as development-only.

## 54. First implementation sequence

Do not generate the entire application in one enormous response.

Work in vertical slices.

Phase 1:

* repository setup
* pyproject
* FastAPI skeleton
* configuration
* database connection
* health endpoint
* Alembic
* CI
* basic tests

Phase 2:

* user model
* passwordless authentication foundation
* sessions
* authenticated `/me`

Phase 3:

* campaigns
* products
* campaign/product relationships

Phase 4:

* product codes
* code normalization
* redemption transaction
* idempotency
* score ledger

Phase 5:

* scoring engine
* rule versions
* campaign scoring configuration

Phase 6:

* spreadsheet import pipeline

Phase 7:

* anti-abuse/risk engine
* rate limiting foundations

Phase 8:

* admin API
* audit logs

Phase 9:

* production hardening
* observability
* Render deployment
* database migration workflow

Phase 10:

* full integration/security testing
* documentation
* demo seed data

## 55. How you should work with me

You are not allowed to silently invent requirements.

When a design decision is genuinely ambiguous, choose a reasonable default and explicitly document the assumption rather than stopping the implementation.

Do not ask me dozens of questions before producing useful code.

Implement one coherent vertical slice at a time.

For every implementation task:

1. State the design decision briefly.
2. Explain which files will be created/changed.
3. Generate the actual code.
4. Generate tests.
5. Generate migration(s) where needed.
6. Explain how to run it.
7. Explain any security implications.
8. Explain any known limitations.
9. Give me the next recommended implementation step.

Do not provide pseudo-code when production-quality code is reasonably possible.

Do not generate placeholder functions such as:

`pass`
`TODO: implement`
`raise NotImplementedError`

unless the abstraction genuinely must remain abstract.

Do not generate fake implementations pretending that an external service works.

## 56. Code quality expectations

Code should be:

* typed
* readable
* modular
* testable
* deterministic where possible
* explicit about failure modes
* secure by default

Favor composition over giant classes.

Keep functions reasonably small.

Avoid clever code when explicit code is easier to audit.

Use domain terminology consistently.

Do not duplicate business logic between API routes.

## 57. Important rule about scoring

The score itself is NOT the product truth.

The ledger is the historical truth.

A displayed passport total can be calculated from the ledger or maintained as a carefully synchronized derived value.

This distinction must remain throughout the implementation.

## 58. Important rule about campaign rules

Anything likely to change because of marketing/business decisions should be configuration or versioned data rather than compiled logic.

Examples:

* point values
* multipliers
* campaign dates
* eligible products
* winning-number rules
* milestones
* bonuses
* limits

Code should define mechanisms.
Data/configuration should define campaign behavior.

## 59. Important rule about correctness

Whenever correctness and convenience conflict, correctness wins for:

* authentication
* redemption
* score calculation
* ledger writes
* campaign eligibility
* authorization

A slightly slower but correct redemption transaction is preferable to a fast implementation that can award duplicate points.

## 60. Final deliverable

The repository should eventually be a clean, deployable project that another developer can clone and run.

The first milestone is not "many endpoints".

The first milestone is:

A user can authenticate.
A campaign exists.
A product exists.
A valid product code exists.
The user can submit the code.
The backend safely validates and redeems it.
The correct configurable scoring rule is applied.
The user's passport reflects the resulting ledger entry.
The operation is tested.
Duplicate/concurrent redemption is prevented.
CI verifies the implementation.
The service can be deployed to Render.

Start with Phase 1 now.

Do not skip tests or migrations in order to move faster.
