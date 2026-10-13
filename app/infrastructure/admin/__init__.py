"""Back office (SQLAdmin) mounted at ``/admin``. ADR-0008 as amended.

Step 1 of B20: phone sign-in for users with the ``admin`` role, and read-only
views. Every write (coin adjustments, approvals) arrives in later steps and
goes through an application service plus the audit log, never a raw edit.
"""

import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import AsyncEngine
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
from app.infrastructure.postgres.models import (
    CodeBatchModel,
    CoinLedgerEntryModel,
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
    column_list = [
        VenueModel.id,
        VenueModel.name,
        VenueModel.city,
        VenueModel.address,
        VenueModel.active,
    ]
    column_labels = {VenueModel.city: "location city"}
    column_searchable_list = [VenueModel.id, VenueModel.name]


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


VIEWS: tuple[type[ModelView], ...] = (
    UserAdmin,
    VenueAdmin,
    CodeBatchAdmin,
    WalletAdmin,
    CoinLedgerAdmin,
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
    )
    for view in VIEWS:
        admin.add_view(view)
    return admin
