"""Back office (SQLAdmin) mounted at ``/admin``. ADR-0008 as amended.

Step 1 of B20: phone sign-in for users with the ``admin`` role, and read-only
views. Step 2: an audit row for every write (SQLAdmin's own audit backend
for generic CRUD, like the venues edit below; the application's unit of
work for a multi-table action, like coin adjustments). No write happens as
a raw edit outside these two paths.
"""

import secrets
import time
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlencode
from uuid import UUID

from sqladmin import Admin, BaseView, DBAuditBackend, Flash, ModelView, expose
from sqladmin.audit import AuditEntry
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.application.authentication import (
    AuthenticationError,
    AuthenticationService,
    DailyLimitError,
    PhoneInvalidError,
    ResendCooldownError,
)
from app.application.coin_adjustments import (
    CoinAdjustmentService,
    InsufficientCoinsError,
    PhoneNumberError,
    UserNotFoundError,
)
from app.infrastructure.postgres.models import (
    AuditLogModel,
    AvatarModel,
    CodeBatchModel,
    CoinLedgerEntryModel,
    RewardRuleModel,
    UserModel,
    VenueModel,
    WalletModel,
)

ADMIN_COOKIE_NAME = "lottery_passport_admin"
ADMIN_PATH = "/admin"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Even an active admin signs in again after this, whatever the idle timeout.
ABSOLUTE_SESSION_SECONDS = 8 * 3600


class PhoneSignInBackend(AuthenticationBackend):
    """Two-step sign-in: phone number, then the SMS code. Admins only.

    The session cookie is separate from the player cookie (``Path=/admin``,
    ``SameSite=Strict``, ``HttpOnly``), signed, and expires after
    ``max_age`` seconds without a request. Role and status are re-read from the
    database on every request, so a demotion ends access immediately.
    """

    def __init__(
        self,
        service: AuthenticationService,
        secret_key: str,
        max_age_seconds: int,
        secure: bool,
        show_test_codes: bool,
    ) -> None:
        self.service = service
        self.show_test_codes = show_test_codes
        self.middlewares = [
            Middleware(
                SessionMiddleware,
                secret_key=secret_key,
                session_cookie=ADMIN_COOKIE_NAME,
                max_age=max_age_seconds,
                path=ADMIN_PATH,
                same_site="strict",
                https_only=secure,
            )
        ]

    async def login(self, request: Request) -> Response | bool:
        form = await request.form()
        if form.get("action") == "verify":
            return await self._verify(request, str(form.get("code") or "").strip())
        return await self._send(request, str(form.get("phone") or "").strip())

    async def _send(self, request: Request, phone: str) -> Response:
        request.session.clear()
        try:
            result = await self.service.request_admin_challenge(phone)
        except PhoneInvalidError:
            return _to_login(request, m="phone")
        except ResendCooldownError as error:
            return _to_login(request, m="wait", s=str(error.retry_after_seconds))
        except DailyLimitError:
            return _to_login(request, m="limit")
        except AuthenticationError:
            return _to_login(request, m="sms")
        request.session["pending_phone"] = phone
        # TODO: remove this on production (otp_test_numbers.py): only set for
        # 0969 test numbers in development/demo.
        if self.show_test_codes and result.test_code:
            request.session["test_code"] = result.test_code
        return _to_login(request, step="code", m="sent")

    async def _verify(self, request: Request, code: str) -> Response | bool:
        phone = request.session.get("pending_phone")
        if not phone:
            return _to_login(request)
        try:
            user = await self.service.verify_admin_challenge(phone, code)
        except AuthenticationError:
            return _to_login(request, step="code", m="bad")
        # A new session for the signed-in admin; nothing from before survives.
        request.session.clear()
        request.session["uid"] = str(user.id)
        request.session["iat"] = int(time.time())
        return True

    async def logout(self, request: Request) -> Response | bool:
        request.session.clear()
        return False

    async def authenticate(self, request: Request) -> Response | bool:
        uid = request.session.get("uid")
        issued_at = request.session.get("iat")
        if not uid or not isinstance(issued_at, int):
            return False
        if time.time() - issued_at > ABSOLUTE_SESSION_SECONDS:
            request.session.clear()
            return False
        try:
            admin = await self.service.get_active_admin(UUID(uid))
        except ValueError:
            admin = None
        if admin is None:
            request.session.clear()
            return False
        return True

    async def get_user_id(self, request: Request) -> Any:
        return request.session.get("uid")


def _to_login(request: Request, **query: str) -> RedirectResponse:
    url = str(request.url_for("admin:login"))
    if query:
        url = f"{url}?{urlencode(query)}"
    return RedirectResponse(url, status_code=303)


class ReadOnlyView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False
    # Exports would put phone numbers in files on laptops; off until needed.
    can_export = False
    page_size = 50


class UserAdmin(ReadOnlyView, model=UserModel):
    name = "Player"
    name_plural = "Players"
    icon = "fa-solid fa-user"
    column_list = [
        UserModel.identifier,
        UserModel.nickname,
        UserModel.role,
        UserModel.account_status,
        UserModel.home_venue_id,
        UserModel.terms_version,
        UserModel.created_at,
    ]
    column_details_exclude_list = [UserModel.nickname_key]
    column_searchable_list = [UserModel.identifier, UserModel.nickname]
    column_sortable_list = [UserModel.created_at, UserModel.nickname]
    column_default_sort = (UserModel.created_at, True)


class VenueAdmin(ReadOnlyView, model=VenueModel):
    name = "Lounge"
    name_plural = "Lounges"
    icon = "fa-solid fa-gamepad"
    # Editable (B20 step 2): fields the panel can fill in as they become
    # known (``address`` is often null at first). ``city`` stays CLI-only
    # (``scripts.venues set --city``): it is one of four fixed ids and the
    # panel has no dropdown widget to constrain free text to them.
    can_edit = True
    column_list = [
        VenueModel.id,
        VenueModel.name,
        VenueModel.city,
        VenueModel.address,
        VenueModel.active,
    ]
    column_labels = {VenueModel.city: "location city"}
    column_searchable_list = [VenueModel.id, VenueModel.name]
    form_columns = [
        VenueModel.name,
        VenueModel.address,
        VenueModel.public_ip,
        VenueModel.active,
    ]


class CodeBatchAdmin(ReadOnlyView, model=CodeBatchModel):
    name = "Code batch"
    name_plural = "Code batches"
    icon = "fa-solid fa-qrcode"
    column_list = [
        CodeBatchModel.label,
        CodeBatchModel.city,
        CodeBatchModel.quantity,
        CodeBatchModel.coins_per_code,
        CodeBatchModel.status,
        CodeBatchModel.created_at,
        CodeBatchModel.activated_at,
    ]
    column_labels = {CodeBatchModel.city: "flavor (passport city)"}
    column_searchable_list = [CodeBatchModel.label]
    column_default_sort = (CodeBatchModel.created_at, True)


class WalletAdmin(ReadOnlyView, model=WalletModel):
    name = "Wallet"
    name_plural = "Wallets"
    icon = "fa-solid fa-wallet"
    column_list = [
        WalletModel.user_id,
        WalletModel.balance,
        WalletModel.lifetime_earned,
        WalletModel.updated_at,
    ]
    column_sortable_list = [WalletModel.balance, WalletModel.lifetime_earned]
    column_default_sort = (WalletModel.balance, True)


class CoinLedgerAdmin(ReadOnlyView, model=CoinLedgerEntryModel):
    name = "Coin ledger entry"
    name_plural = "Coin ledger"
    icon = "fa-solid fa-coins"
    column_list = [
        CoinLedgerEntryModel.created_at,
        CoinLedgerEntryModel.user_id,
        CoinLedgerEntryModel.amount,
        CoinLedgerEntryModel.reason,
        CoinLedgerEntryModel.source_id,
        CoinLedgerEntryModel.note,
    ]
    column_searchable_list = [CoinLedgerEntryModel.reason]
    column_default_sort = (CoinLedgerEntryModel.created_at, True)


class AvatarAdmin(ModelView, model=AvatarModel):
    """Avatar catalogue (P1): starts empty, filled in here. ``locked``
    avatars show up but ``PATCH /me avatar_id`` refuses picking them
    (422 AVATAR_LOCKED) until an unlock rule exists (AFTER LAUNCH)."""

    name = "Avatar"
    name_plural = "Avatars"
    icon = "fa-solid fa-image"
    can_create = True
    can_edit = True
    can_delete = False
    can_export = False
    column_list = [
        AvatarModel.id,
        AvatarModel.image_url,
        AvatarModel.locked,
        AvatarModel.sort,
        AvatarModel.active,
    ]
    column_searchable_list = [AvatarModel.id]
    column_default_sort = (AvatarModel.sort, False)
    form_columns = [
        AvatarModel.id,
        AvatarModel.image_url,
        AvatarModel.locked,
        AvatarModel.unlock_rule,
        AvatarModel.sort,
        AvatarModel.active,
    ]


class RewardRuleAdmin(ModelView, model=RewardRuleModel):
    """Admin-tunable reward amounts (ADR 0010): no deploy to retune a
    reward or turn it off.

    ``key`` is picked by whichever service reads it (for example
    ``first_code``, the welcome bonus) -- there is no catalogue of valid
    keys here by design; a typo'd key is simply never read by anything,
    same risk profile as an unused row. No delete: switch a rule off with
    ``active = false`` instead, so its history (and anything that already
    decided based on it) stays legible.
    """

    name = "Reward rule"
    name_plural = "Reward rules"
    icon = "fa-solid fa-sliders"
    can_create = True
    can_edit = True
    can_delete = False
    can_export = False
    column_list = [
        RewardRuleModel.key,
        RewardRuleModel.amount,
        RewardRuleModel.cadence,
        RewardRuleModel.active,
        RewardRuleModel.note,
        RewardRuleModel.updated_at,
    ]
    column_searchable_list = [RewardRuleModel.key]
    form_columns = [
        RewardRuleModel.key,
        RewardRuleModel.amount,
        RewardRuleModel.cadence,
        RewardRuleModel.active,
        RewardRuleModel.note,
    ]


VIEWS: tuple[type[ModelView], ...] = (
    UserAdmin,
    VenueAdmin,
    CodeBatchAdmin,
    WalletAdmin,
    CoinLedgerAdmin,
    AvatarAdmin,
    RewardRuleAdmin,
)


class SqlAdminAuditBackend(DBAuditBackend):
    """Writes SQLAdmin's own CRUD audit entries into our ``audit_log`` table.

    Best-effort, in its OWN transaction: SQLAdmin calls this after the edit
    already committed (see ``ModelView._emit_audit``), matching its documented
    trade-off that a broken audit backend must never undo an already-committed
    admin change. A write that must be atomic with its audit row (coin
    adjustments) goes through ``CoinAdjustmentService``'s unit of work
    instead, never through this backend.
    """

    def build_row(
        self, entry: AuditEntry, actor: Any, request: Request
    ) -> AuditLogModel:
        # ``actor`` is None only if a write somehow ran without an
        # authenticated admin, which ``authenticate()`` already prevents;
        # UUID(None) raises, and the caller (_emit_audit) logs it rather
        # than lose the already-committed change.
        return AuditLogModel(
            actor_user_id=UUID(str(actor)),
            action=entry.action,
            entity=entry.identity,
            entity_id=entry.pk,
            changes=entry.changes,
            ip=request.client.host if request.client else None,
            created_at=entry.timestamp,
        )


class CoinAdjustmentView(BaseView):
    """A small custom page (not a model list) for giving or taking coins.

    Goes through ``CoinAdjustmentService`` -- ledger entry, wallet and audit
    row in one transaction -- never a raw ``UPDATE`` on ``wallets``.
    ``service`` is a class attribute set once in :func:`mount_admin`
    (SQLAdmin instantiates views with no constructor arguments, the same
    reason it injects ``session_maker`` onto ``ModelView`` subclasses after
    the fact rather than through ``__init__``).
    """

    name = "Adjust coins"
    identity = "coin-adjustments"
    icon = "fa-solid fa-coins"
    service: ClassVar[CoinAdjustmentService]

    @expose("/coin-adjustments", methods=["GET", "POST"], identity="coin-adjustments")
    async def form(self, request: Request) -> Response:
        if request.method == "POST":
            await self._submit(request)
            return RedirectResponse(
                request.url_for("admin:view-coin-adjustments"), status_code=303
            )
        return await self.templates.TemplateResponse(
            request, "sqladmin/coin_adjustment.html", {}
        )

    async def _submit(self, request: Request) -> None:
        admin_id = request.session.get("uid")
        if not admin_id:
            Flash.error(request, "Session expired; sign in again.")
            return
        data = await request.form()
        identifier = str(data.get("identifier") or "").strip()
        note = str(data.get("note") or "").strip()
        amount_raw = str(data.get("amount") or "").strip()
        try:
            amount = int(amount_raw)
        except ValueError:
            Flash.error(request, "Amount must be a whole number.")
            return
        if amount == 0:
            Flash.error(request, "Amount must not be zero.")
            return
        if not note:
            Flash.error(request, "A note (reason) is required.")
            return
        if len(note) > 500:
            Flash.error(request, "Note is too long (500 characters max).")
            return
        try:
            result = await self.service.adjust(
                actor_id=UUID(admin_id),
                target_identifier=identifier,
                amount=amount,
                note=note,
                ip=request.client.host if request.client else None,
            )
        except PhoneNumberError:
            Flash.error(request, "That is not a valid Iranian mobile number.")
        except UserNotFoundError:
            Flash.error(request, f"No player with phone number {identifier!r}.")
        except InsufficientCoinsError:
            Flash.error(request, "That would take the balance below zero.")
        except ValueError as error:
            Flash.error(request, str(error))
        else:
            verb = "Gave" if amount > 0 else "Took"
            Flash.success(
                request,
                f"{verb} {abs(amount)} coins for {identifier}. "
                f"New balance: {result.new_balance}.",
            )


def mount_admin(
    app: Starlette,
    engine: AsyncEngine,
    service: AuthenticationService,
    *,
    secret_key: str | None,
    max_age_seconds: int,
    secure: bool,
    show_test_codes: bool,
    session_factory: async_sessionmaker[AsyncSession],
    coin_adjustment_service: CoinAdjustmentService,
) -> Admin:
    backend = PhoneSignInBackend(
        service,
        # Unset (development, demo): a fresh key per process, so admin
        # sessions end when the process restarts. Config refuses this in
        # staging/production, where several workers must share one key.
        secret_key=secret_key or secrets.token_urlsafe(48),
        max_age_seconds=max_age_seconds,
        secure=secure,
        show_test_codes=show_test_codes,
    )
    admin = Admin(
        app,
        engine,
        base_url=ADMIN_PATH,
        title="TorshX admin",
        authentication_backend=backend,
        templates_dir=str(TEMPLATES_DIR),
        audit_backend=SqlAdminAuditBackend(session_factory),
    )
    for view in VIEWS:
        admin.add_view(view)
    CoinAdjustmentView.service = coin_adjustment_service
    admin.add_view(CoinAdjustmentView)
    return admin
