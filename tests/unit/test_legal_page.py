"""``GET /legal/{version}`` (LG1'): the page renderer and the route, without a
database. The seed, the freeze trigger and the admin tab are exercised
against PostgreSQL in tests/integration/test_legal_documents_db.py."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_legal_document_service
from app.api.legal import render_legal_page
from app.app import create_app
from app.core.config import Settings
from app.domain.legal import LegalDocument

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

BODY = """# قوانین TorshX

نسخه: 2026-10-20

## ۱. قوانین {#terms}

۱.۱ یک خط
که ادامه دارد.

---

## ۲. حریم خصوصی {#privacy}

۲.۱ داده‌ها:
   - شماره موبایل
   - کد ورود، که
     چند دقیقه منقضی می‌شود

پاراگراف آخر.
"""


def document(body: str = BODY) -> LegalDocument:
    return LegalDocument(version="2026-10-20", body=body, updated_at=NOW)


def test_the_page_is_right_to_left_persian() -> None:
    page = render_legal_page(document())

    assert page.startswith('<!doctype html><html lang="fa" dir="rtl">')
    assert "<title>قوانین TorshX</title>" in page
    assert '<meta name="viewport"' in page


def test_headings_keep_their_anchors_so_privacy_url_can_jump_there() -> None:
    page = render_legal_page(document())

    assert "<h1>قوانین TorshX</h1>" in page
    assert '<h2 id="terms">۱. قوانین</h2>' in page
    assert '<h2 id="privacy">۲. حریم خصوصی</h2>' in page
    assert "{#" not in page


def test_paragraphs_lists_and_rules() -> None:
    page = render_legal_page(document())

    assert "<p>۱.۱ یک خط که ادامه دارد.</p>" in page
    assert "<hr>" in page
    assert (
        "<p>۲.۱ داده‌ها:</p><ul><li>شماره موبایل</li>"
        "<li>کد ورود، که چند دقیقه منقضی می‌شود</li></ul><p>پاراگراف آخر.</p>"
    ) in page


def test_markup_typed_into_the_admin_panel_is_escaped() -> None:
    page = render_legal_page(
        document('# <script>alert(1)</script>\n\n## x {#"><b>}\n\n<img src=x>')
    )

    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    assert "<img" not in page
    # Not a valid anchor id, so it stays (escaped) text, never an attribute.
    assert 'id="' not in page


class FakeLegalDocumentService:
    def __init__(self, known: LegalDocument | None) -> None:
        self.known = known

    async def get(self, version: str) -> LegalDocument | None:
        if self.known is not None and self.known.version == version:
            return self.known
        return None


def client(service: FakeLegalDocumentService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_legal_document_service] = lambda: service
    return TestClient(app)


def test_a_known_version_is_an_html_page_without_sign_in() -> None:
    response = client(FakeLegalDocumentService(document())).get("/legal/2026-10-20")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="privacy"' in response.text


def test_an_unknown_version_is_404() -> None:
    response = client(FakeLegalDocumentService(document())).get("/legal/2099-01-01")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_version_outside_the_alphabet_never_reaches_the_service() -> None:
    response = client(FakeLegalDocumentService(document())).get("/legal/a.b")

    assert response.status_code == 422
