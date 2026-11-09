from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.knowledge import services
from apps.knowledge.models import KnowledgeChunk, KnowledgeSource
from common.safe_http import SafeResponse, UnsafeURLError, validate_url
from tests.helpers import make_pdf, set_plan

FAQ = [
    {"question": "Do you ship to Pune?", "answer": "Yes, we ship across India including Pune within 3 business days."},
    {"question": "What is your refund policy?", "answer": "Refunds are processed within 5 days of receiving the item."},
    {"question": "Do you offer gift wrapping?", "answer": "Gift wrapping is available for 99 rupees per order."},
]


@pytest.fixture
def kbase(tenant_a) -> str:
    return f"/api/v1/workspaces/{tenant_a.workspace.id}/knowledge"


def _create(client, kbase, django_capture_on_commit_callbacks, **data):  # type: ignore[no-untyped-def]
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{kbase}/sources/", data, format="json" if "file" not in data else None)
    assert response.status_code == 201, response.json()
    return KnowledgeSource.objects.get(id=response.json()["id"])


class TestIngestion:
    def test_faq_text_and_files_are_chunked_and_embedded(
        self, client_for, tenant_a, kbase, django_capture_on_commit_callbacks
    ):
        client = client_for(tenant_a.owner)
        faq = _create(client, kbase, django_capture_on_commit_callbacks, kind="faq", title="Store FAQ", faq=FAQ)
        text = _create(
            client,
            kbase,
            django_capture_on_commit_callbacks,
            kind="text",
            title="About",
            text="We are open 9am-6pm IST.",
        )
        pdf = _create(
            client,
            kbase,
            django_capture_on_commit_callbacks,
            kind="file",
            file=SimpleUploadedFile("policy.pdf", make_pdf("Warranty lasts two years from purchase")),
        )
        md = _create(
            client,
            kbase,
            django_capture_on_commit_callbacks,
            kind="file",
            file=SimpleUploadedFile("guide.md", b"# Setup\n\nPlug it in."),
        )
        for source in (faq, text, pdf, md):
            source.refresh_from_db()
            assert source.status == "ready", (source.title, source.error)
            assert source.chunk_count == source.chunks.count() > 0
            assert source.embedding_model == "hashing-v1"
        assert faq.chunk_count == 3  # one chunk per Q/A
        assert "Warranty lasts two years" in pdf.chunks.first().content
        assert pdf.chunks.first().metadata["page"] == 1
        assert pdf.title == "policy.pdf"

    def test_long_text_chunks_with_overlap(self, tenant_a):
        from apps.knowledge.processing import CHUNK_TARGET_CHARS, Section, chunk_sections

        text = " ".join(f"Sentence number {i} explains a detail." for i in range(400))
        chunks = chunk_sections([Section(text)])
        assert len(chunks) > 5
        assert all(len(c.text) <= CHUNK_TARGET_CHARS + 200 for c in chunks)

    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("evil.exe", b"MZ\x90"),
            ("fake.pdf", b"<html>not a pdf</html>"),
            ("img.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20),
        ],
    )
    def test_invalid_files_rejected(self, client_for, tenant_a, kbase, name, content):
        r = client_for(tenant_a.owner).post(
            f"{kbase}/sources/", {"kind": "file", "file": SimpleUploadedFile(name, content)}
        )
        assert r.status_code == 400 and "file" in r.json()["error"]["details"]
        assert not KnowledgeSource.objects.exists()

    def test_failed_extraction_marks_source_failed(
        self, client_for, tenant_a, kbase, django_capture_on_commit_callbacks
    ):
        source = _create(
            client_for(tenant_a.owner),
            kbase,
            django_capture_on_commit_callbacks,
            kind="file",
            file=SimpleUploadedFile("broken.pdf", b"%PDF-1.4 garbage"),
        )
        source.refresh_from_db()
        assert source.status == "failed" and source.error

    def test_url_ingestion_uses_safe_fetch(
        self, client_for, tenant_a, kbase, django_capture_on_commit_callbacks, monkeypatch
    ):
        html = (
            b"<html><head><title>Shipping info</title></head><body><nav>menu</nav>"
            b"<main>We ship worldwide.</main><script>evil()</script></body></html>"
        )
        monkeypatch.setattr(
            services, "safe_request", lambda *a, **k: SafeResponse("https://example.com/ship", 200, "text/html", html)
        )
        monkeypatch.setattr("apps.knowledge.api.validate_url", lambda url: url)
        source = _create(
            client_for(tenant_a.owner),
            kbase,
            django_capture_on_commit_callbacks,
            kind="url",
            url="https://example.com/ship",
        )
        source.refresh_from_db()
        assert source.status == "ready" and source.title == "Shipping info"
        content = source.chunks.first().content
        assert "We ship worldwide." in content and "evil" not in content and "menu" not in content


class TestSSRF:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/admin",
            "http://127.0.0.1:8000/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/",
            "http://[::1]/",
            "file:///etc/passwd",
            "https://user:pass@example.com/",
            "gopher://example.com/",
        ],
    )
    def test_private_and_odd_urls_rejected(self, url, settings):
        settings.DEBUG = True  # even with http allowed
        with pytest.raises(UnsafeURLError):
            validate_url(url)

    def test_http_rejected_outside_debug(self, settings):
        settings.DEBUG = False
        with pytest.raises(UnsafeURLError):
            validate_url("http://example.com/")

    def test_api_rejects_private_url(self, client_for, tenant_a, kbase):
        r = client_for(tenant_a.owner).post(
            f"{kbase}/sources/", {"kind": "url", "url": "http://127.0.0.1/"}, format="json"
        )
        assert r.status_code == 400 and "url" in r.json()["error"]["details"]


class TestRetrieval:
    @pytest.fixture
    def sources(self, client_for, tenant_a, kbase, django_capture_on_commit_callbacks):  # type: ignore[no-untyped-def]
        client = client_for(tenant_a.owner)
        faq = _create(
            client,
            kbase,
            django_capture_on_commit_callbacks,
            kind="faq",
            title="FAQ",
            faq=FAQ,
            metadata={"area": "orders"},
        )
        other = _create(
            client,
            kbase,
            django_capture_on_commit_callbacks,
            kind="text",
            title="Careers",
            text="We are hiring engineers in Bengaluru.",
        )
        return faq, other

    def test_relevant_chunk_ranks_first(self, client_for, tenant_a, kbase, sources):
        r = client_for(tenant_a.ws_viewer).post(
            f"{kbase}/search/", {"query": "how long do refunds take?"}, format="json"
        )
        assert r.status_code == 200
        assert "Refunds are processed" in r.json()[0]["content"]
        assert r.json()[0]["score"] > r.json()[-1]["score"]

    def test_filters(self, client_for, tenant_a, kbase, sources):
        faq, other = sources
        client = client_for(tenant_a.owner)
        only_other = client.post(
            f"{kbase}/search/", {"query": "refunds", "source_ids": [str(other.id)]}, format="json"
        ).json()
        assert {r["source_id"] for r in only_other} == {str(other.id)}
        by_meta = client.post(
            f"{kbase}/search/", {"query": "hiring", "metadata": {"area": "orders"}}, format="json"
        ).json()
        assert {r["source_id"] for r in by_meta} == {str(faq.id)}
        client.patch(f"{kbase}/sources/{faq.id}/", {"enabled": False}, format="json")
        disabled = client.post(f"{kbase}/search/", {"query": "refunds"}, format="json").json()
        assert all(r["source_id"] != str(faq.id) for r in disabled)

    def test_search_never_crosses_workspaces(self, tenant_a, tenant_b, sources):
        assert services.search(workspace=tenant_b.workspace, query="refunds") == []
        # Even passing A's source ids explicitly from B's workspace yields nothing.
        assert services.search(workspace=tenant_b.workspace, query="refunds", source_ids=[sources[0].id]) == []

    def test_chunks_from_other_embedding_models_are_ignored(self, tenant_a, sources):
        KnowledgeChunk.objects.update(embedding_model="openai:text-embedding-3-small")
        assert services.search(workspace=tenant_a.workspace, query="refunds") == []

    def test_reindex_and_delete(self, client_for, tenant_a, kbase, sources, django_capture_on_commit_callbacks):
        faq, _ = sources
        client = client_for(tenant_a.owner)
        with django_capture_on_commit_callbacks(execute=True):
            assert client.post(f"{kbase}/sources/{faq.id}/reindex/").status_code == 202
        faq.refresh_from_db()
        assert faq.status == "ready" and faq.chunks.count() == 3
        assert client.get(f"{kbase}/sources/{faq.id}/chunks/").json()["count"] == 3
        assert client.delete(f"{kbase}/sources/{faq.id}/").status_code == 204
        assert not KnowledgeChunk.objects.filter(source_id=faq.id).exists()


class TestKnowledgeAccess:
    def test_isolation_and_roles(self, client_for, tenant_a, tenant_b, kbase, django_capture_on_commit_callbacks):
        source = _create(
            client_for(tenant_a.owner),
            kbase,
            django_capture_on_commit_callbacks,
            kind="text",
            title="T",
            text="secret pricing",
        )
        b = client_for(tenant_b.owner)
        assert b.get(f"{kbase}/sources/").status_code == 404
        b_base = f"/api/v1/workspaces/{tenant_b.workspace.id}/knowledge"
        assert b.get(f"{b_base}/sources/{source.id}/").status_code == 404
        assert b.delete(f"{b_base}/sources/{source.id}/").status_code == 404
        assert b.post(f"{b_base}/search/", {"query": "secret pricing"}, format="json").json() == []
        viewer = client_for(tenant_a.ws_viewer)
        assert viewer.get(f"{kbase}/sources/").status_code == 200
        assert (
            viewer.post(f"{kbase}/sources/", {"kind": "text", "title": "x", "text": "y"}, format="json").status_code
            == 403
        )

    def test_storage_quota_enforced(self, client_for, tenant_a, kbase):
        set_plan(tenant_a.org, "starter", knowledge_mb=0)
        r = client_for(tenant_a.owner).post(
            f"{kbase}/sources/", {"kind": "text", "title": "x", "text": "y" * 100}, format="json"
        )
        assert r.status_code == 402 and r.json()["error"]["code"] == "plan_limit_reached"
