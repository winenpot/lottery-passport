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
from sqladmin.filters import AllUniqueStringValuesFilter, StaticValuesFilter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
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
from app.application.media import MediaService
from app.domain.legal import LEGAL_VERSION_PATTERN
from app.domain.media import MediaError, MediaRefusal, extension_for
from app.infrastructure.postgres.models import (
    AchievementModel,
    AuditLogModel,
    AvatarModel,
    ChallengeModel,
    CodeBatchModel,
    CoinLedgerEntryModel,
    LegalDocumentModel,
    MiniGameRunModel,
    RewardRuleModel,
    UserAchievementModel,
    UserModel,
    VenueModel,
    WalletModel,
)

ADMIN_COOKIE_NAME = "lottery_passport_admin"
ADMIN_PATH = "/admin"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Even an active admin signs in again after this, whatever the idle timeout.
ABSOLUTE_SESSION_SECONDS = 8 * 3600
# Wrong TOTP codes before the whole sign-in attempt (phone step included)
# must restart: a human mistypes at most a couple of times; past that it
# looks like guessing against a 6-digit, 90-second-window space.
MAX_TOTP_ATTEMPTS_PER_SIGN_IN = 5


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
        action = form.get("action")
        if action == "verify":
            return await self._verify(request, str(form.get("code") or "").strip())
        if action == "verify_totp":
            return await self._verify_totp(request, str(form.get("code") or "").strip())
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
        if await self.service.has_confirmed_admin_totp(user.id):
            # Not signed in yet: only a pending marker, no `uid`/`iat`, so
            # `authenticate()` still refuses this session until the TOTP
            # step below also succeeds.
            request.session.clear()
            request.session["totp_pending_uid"] = str(user.id)
            request.session["totp_attempts"] = 0
            return _to_login(request, step="totp")
        # No second factor enrolled: unchanged, single-factor sign-in.
        request.session.clear()
        request.session["uid"] = str(user.id)
        request.session["iat"] = int(time.time())
        return True

    async def _verify_totp(self, request: Request, code: str) -> Response | bool:
        pending_uid = request.session.get("totp_pending_uid")
        if not pending_uid:
            return _to_login(request)
        try:
            await self.service.verify_admin_totp(UUID(pending_uid), code)
        except (AuthenticationError, ValueError):
            attempts = int(request.session.get("totp_attempts", 0)) + 1
            if attempts >= MAX_TOTP_ATTEMPTS_PER_SIGN_IN:
                request.session.clear()
                return _to_login(request, m="totp_locked")
            request.session["totp_attempts"] = attempts
            return _to_login(request, step="totp", m="totp_bad")
        request.session.clear()
        request.session["uid"] = pending_uid
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


class MiniGameRunAdmin(ReadOnlyView, model=MiniGameRunModel):
    """W11: "performance saved, cheating watched" made visible in the panel.

    ``status`` is the stored verdict (open/accepted/rejected/expired); the
    *why* behind a rejection (app/domain/mini_games.py's ``MiniGameRunRejection``)
    is computed at finish time and returned in the API response but never
    persisted on this row, so it cannot be shown here without a migration
    adding a column for it -- out of scope for this read-only view.
    """

    name = "Mini-game run"
    name_plural = "Mini-game runs"
    icon = "fa-solid fa-bolt"
    column_list = [
        MiniGameRunModel.user_id,
        MiniGameRunModel.mini_game_id,
        MiniGameRunModel.status,
        MiniGameRunModel.average_reaction_ms,
        MiniGameRunModel.issued_at,
        MiniGameRunModel.finished_at,
    ]
    column_filters = [
        StaticValuesFilter(
            MiniGameRunModel.status,
            [
                ("open", "open"),
                ("accepted", "accepted"),
                ("rejected", "rejected"),
                ("expired", "expired"),
            ],
            title="Status",
        ),
        AllUniqueStringValuesFilter(MiniGameRunModel.user_id, title="Player"),
    ]
    column_sortable_list = [
        MiniGameRunModel.issued_at,
        MiniGameRunModel.average_reaction_ms,
    ]
    column_default_sort = (MiniGameRunModel.issued_at, True)


class AvatarAdmin(ModelView, model=AvatarModel):
    """Avatar catalogue (P1): starts empty, filled in here. ``locked``
    avatars show up but ``PATCH /me avatar_id`` refuses picking them
    (422 AVATAR_LOCKED) until an unlock rule exists (AFTER LAUNCH)."""

    name = "Avatar"
    name_plural = "Avatars"
    icon = "fa-solid fa-image"
    can_create = True
    # The id/key is typed by the admin; SQLAdmin hides primary keys otherwise.
    form_include_pk = True
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
    # The id/key is typed by the admin; SQLAdmin hides primary keys otherwise.
    form_include_pk = True
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


class ChallengeAdmin(ModelView, model=ChallengeModel):
    """Challenge catalogue (C1): starts empty, filled in here. ``kind``
    must be one of the three app/domain/challenges.py knows how to check
    progress for (``team_choice``, ``distinct_flavors``, ``daily_checkin``)
    -- the DB CHECK enforces this, there is no dropdown widget for it here.
    No delete: a challenge with claim history cannot be deleted anyway (FK
    ON DELETE RESTRICT); switch it off with ``active = false`` instead.
    """

    name = "Challenge"
    name_plural = "Challenges"
    icon = "fa-solid fa-flag-checkered"
    can_create = True
    # The id/key is typed by the admin; SQLAdmin hides primary keys otherwise.
    form_include_pk = True
    can_edit = True
    can_delete = False
    can_export = False
    column_list = [
        ChallengeModel.id,
        ChallengeModel.kind,
        ChallengeModel.period,
        ChallengeModel.target,
        ChallengeModel.reward_coins,
        ChallengeModel.active,
    ]
    column_searchable_list = [ChallengeModel.id]
    form_columns = [
        ChallengeModel.id,
        ChallengeModel.kind,
        ChallengeModel.period,
        ChallengeModel.target,
        ChallengeModel.reward_coins,
        ChallengeModel.active,
    ]


class AchievementAdmin(ModelView, model=AchievementModel):
    """Achievement catalogue (AC1 MVP slice): starts empty, filled in here.
    ``fact`` is the one app/domain/achievements.py knows how to check a
    streak against today (``checkin_streak``) -- the DB CHECK enforces
    this. ``threshold`` is a day count (e.g. 3/7/30). Unlocking is
    automatic and pays once per player the moment a ``daily_checkin``
    claim crosses it -- there is no claim button, no badge/image field yet
    (AC1's full spec -- artwork, the approved 8-12 list -- has not
    happened). No delete: an achievement with unlock history cannot be
    deleted anyway (FK ON DELETE RESTRICT); switch it off with
    ``active = false`` instead.
    """

    name = "Achievement"
    name_plural = "Achievements"
    icon = "fa-solid fa-medal"
    can_create = True
    # The id/key is typed by the admin; SQLAdmin hides primary keys otherwise.
    form_include_pk = True
    can_edit = True
    can_delete = False
    can_export = False
    column_list = [
        AchievementModel.id,
        AchievementModel.fact,
        AchievementModel.threshold,
        AchievementModel.reward_coins,
        AchievementModel.active,
    ]
    column_searchable_list = [AchievementModel.id]
    form_columns = [
        AchievementModel.id,
        AchievementModel.fact,
        AchievementModel.threshold,
        AchievementModel.reward_coins,
        AchievementModel.active,
    ]


class UserAchievementAdmin(ReadOnlyView, model=UserAchievementModel):
    """Who unlocked what, and when -- for support, not for editing (the
    ledger entry it paid, if any, is the source of truth for the coins)."""

    name = "Unlocked achievement"
    name_plural = "Unlocked achievements"
    icon = "fa-solid fa-trophy"
    column_list = [
        UserAchievementModel.user_id,
        UserAchievementModel.achievement_id,
        UserAchievementModel.unlocked_at,
    ]
    column_sortable_list = [UserAchievementModel.unlocked_at]
    column_default_sort = (UserAchievementModel.unlocked_at, True)


class LegalDocumentAdmin(ModelView, model=LegalDocumentModel):
    """Terms of use + privacy (LG1'): one row per version, shown publicly at
    ``/legal/<version>``. Players accept the version the server's
    ``TERMS_VERSION`` names. A version any player accepted is frozen (the
    0020 trigger is the guarantee; the check below only makes the refusal
    readable): change the text by creating a new version instead. No
    delete, for the same reason."""

    name = "Terms & privacy"
    name_plural = "Terms & privacy"
    icon = "fa-solid fa-scale-balanced"
    can_create = True
    can_edit = True
    can_delete = False
    can_export = False
    column_list = [LegalDocumentModel.version, LegalDocumentModel.updated_at]
    column_default_sort = (LegalDocumentModel.version, True)
    column_labels = {LegalDocumentModel.body: "text"}
    # SQLAdmin drops primary keys from forms unless told otherwise, and the
    # version is typed by the admin.
    form_include_pk = True
    form_columns = [LegalDocumentModel.version, LegalDocumentModel.body]
    form_widget_args = {
        "body": {
            "rows": 40,
            "dir": "rtl",
            "style": "width: 100%; line-height: 1.8; font-family: Tahoma, sans-serif;",
        }
    }

    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        version = str(data.get("version") or "")
        if not LEGAL_VERSION_PATTERN.match(version):
            raise ValueError(
                "Version: 1-20 letters, digits, '-' or '_' (for example 2026-10-20)."
            )
        if is_created:
            return
        # ``model`` still holds the stored version here (changes apply after).
        async with self.session_maker() as session:
            accepted = await session.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.terms_version == model.version)
            )
        if accepted:
            raise ValueError(
                f"Version {model.version} was accepted by {accepted} player(s) and "
                "can no longer change. Create a new version (for example a new "
                "date) and point TERMS_VERSION at it."
            )


VIEWS: tuple[type[ModelView], ...] = (
    UserAdmin,
    VenueAdmin,
    CodeBatchAdmin,
    WalletAdmin,
    CoinLedgerAdmin,
    MiniGameRunAdmin,
    AvatarAdmin,
    RewardRuleAdmin,
    ChallengeAdmin,
    AchievementAdmin,
    UserAchievementAdmin,
    LegalDocumentAdmin,
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


class AdminTotpSetupView(BaseView):
    """Self-service enrollment for the admin TOTP second factor (docs/
    launch-reports/2026-10-23-handoff.md decision 8).

    GET shows the current state: no secret yet starts enrollment and shows
    it for scanning/manual entry; a pending secret is shown again unchanged
    (AuthenticationService.begin_admin_totp_enrollment reuses it); once
    confirmed there is nothing left to do here -- a lost phone goes through
    ``scripts.admins reset-totp``, a deliberate CLI action, not a click an
    already-hijacked session could make.
    """

    name = "Two-factor (TOTP)"
    identity = "admin-totp-setup"
    icon = "fa-solid fa-key"
    service: ClassVar[AuthenticationService]

    @expose("/security/totp", methods=["GET", "POST"], identity="admin-totp-setup")
    async def form(self, request: Request) -> Response:
        admin_id = request.session.get("uid")
        if not admin_id:
            return RedirectResponse(request.url_for("admin:login"), status_code=303)
        if request.method == "POST":
            await self._confirm(request, UUID(admin_id))
            return RedirectResponse(
                request.url_for("admin:view-admin-totp-setup"), status_code=303
            )
        return await self._render(request, UUID(admin_id))

    async def _render(self, request: Request, admin_id: UUID) -> Response:
        if await self.service.has_confirmed_admin_totp(admin_id):
            return await self.templates.TemplateResponse(
                request, "sqladmin/totp_setup.html", {"enrolled": True}
            )
        secret = await self.service.begin_admin_totp_enrollment(admin_id)
        return await self.templates.TemplateResponse(
            request,
            "sqladmin/totp_setup.html",
            {"enrolled": False, "secret": secret},
        )

    async def _confirm(self, request: Request, admin_id: UUID) -> None:
        data = await request.form()
        code = str(data.get("code") or "").strip()
        try:
            await self.service.confirm_admin_totp_enrollment(admin_id, code)
        except AuthenticationError:
            Flash.error(request, "Wrong or expired code. Scan again and retry.")
        else:
            Flash.success(
                request, "Two-factor sign-in is now required for your account."
            )


_MEDIA_ERROR_MESSAGES: dict[MediaRefusal, str] = {
    MediaRefusal.EMPTY: "Choose a file to upload.",
    MediaRefusal.TOO_LARGE: "That file is larger than 512 KB.",
    MediaRefusal.UNSUPPORTED_TYPE: (
        "Only PNG, JPEG or WebP images are accepted (not SVG, not any other file)."
    ),
}


class MediaUploadView(BaseView):
    """ "Images" page (W10): upload a PNG/JPEG/WebP, get back the same-origin
    URL to paste into an avatar/badge/prize-art row's ``image_url`` field.

    Deliberately not a file field bolted onto those model forms: SQLAdmin
    only renders form fields backed by a real model column, and
    ``image_url`` is (and stays) a plain string column -- upload here, paste
    the URL there, same two-step shape as copying coordinates off a map for
    a venue today. ``service`` is a class attribute, same reason as
    ``CoinAdjustmentView.service`` above.
    """

    name = "Images"
    identity = "media-upload"
    icon = "fa-solid fa-image"
    service: ClassVar[MediaService]

    @expose("/images", methods=["GET", "POST"], identity="media-upload")
    async def form(self, request: Request) -> Response:
        uploaded_url: str | None = None
        if request.method == "POST":
            uploaded_url = await self._submit(request)
        return await self.templates.TemplateResponse(
            request, "sqladmin/media_upload.html", {"uploaded_url": uploaded_url}
        )

    async def _submit(self, request: Request) -> str | None:
        admin_id = request.session.get("uid")
        data = await request.form()
        upload = data.get("file")
        if not isinstance(upload, UploadFile) or not upload.filename:
            Flash.error(request, "Choose a file to upload.")
            return None
        content = await upload.read()
        try:
            asset = await self.service.upload(
                content,
                created_by_user_id=UUID(admin_id) if admin_id else None,
            )
        except MediaError as error:
            Flash.error(request, _MEDIA_ERROR_MESSAGES[error.reason])
            return None
        url = f"/media/{asset.sha256}.{extension_for(asset.content_type)}"
        Flash.success(request, f"Uploaded. URL: {url}")
        return url


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
    media_service: MediaService,
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
    AdminTotpSetupView.service = service
    admin.add_view(AdminTotpSetupView)
    MediaUploadView.service = media_service
    admin.add_view(MediaUploadView)
    return admin
