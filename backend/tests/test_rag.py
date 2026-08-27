"""
Retrieval layer tests.

Two properties carry the design and are tested hardest: patient-scoped
retrieval must not cross patients, and it must leave an audit trail. The
similarity ranking itself is exercised with the deterministic hashing
embedder, so these run offline with no model download.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import IdentityAccessLog
from app.rag import retrieval
from app.rag.chunking import chunk_markdown, deidentify
from app.rag.embeddings import EMBEDDING_DIMENSIONS, HashingEmbedder
from app.rag.ingest import ingest_patient_document, ingest_protocol_dir
from app.rag.models import PatientDocumentChunk, ProtocolChunk
from app.scheduling.models import StaffRole, StaffUser


@pytest.fixture(autouse=True)
def offline_embedder(monkeypatch):
    """Force the deterministic embedder so tests never download a model."""
    import app.rag.ingest as ingest_mod

    for module in (retrieval, ingest_mod):
        monkeypatch.setattr(module, "get_embedder", lambda *a, **k: HashingEmbedder())


class TestChunking:
    def test_splits_on_headings_and_keeps_section_titles(self):
        text = "# Alpha\n\nFirst body.\n\n## Beta\n\nSecond body."
        chunks = chunk_markdown(text)
        assert [t for t, _ in chunks] == ["Alpha", "Beta"]
        assert chunks[0][1] == "First body."

    def test_long_section_splits_on_paragraph_boundaries(self):
        body = "\n\n".join(["word " * 60] * 6)
        chunks = chunk_markdown(f"# Long\n\n{body}", max_chars=500)
        assert len(chunks) > 1
        # No chunk exceeds the budget by more than one paragraph
        assert all(len(c) < 900 for _, c in chunks)

    def test_document_without_headings_still_chunks(self):
        chunks = chunk_markdown("Just a plain paragraph with no heading.")
        assert len(chunks) == 1
        assert chunks[0][1].startswith("Just a plain")


class TestDeidentification:
    def test_replaces_names_with_uuid_token(self):
        pid = uuid.uuid4()
        text = "Jane Doe arrived at 3pm. Jane reported improvement."
        out = deidentify(text, pid, ["Jane", "Doe"])
        assert "Jane" not in out
        assert "Doe" not in out
        assert f"[patient:{pid}]" in out

    def test_is_case_insensitive_and_prefers_longest_match(self):
        pid = uuid.uuid4()
        out = deidentify("MARGARET and Margaret Thompson", pid, ["Margaret", "Margaret Thompson"])
        assert "argaret" not in out

    def test_collapses_the_token_run_left_by_a_full_name(self):
        # Regression: seeded documents rendered "[patient:uuid] [patient:uuid]
        # attended a consultation" because given and family names are replaced
        # independently. Providers read this text, so the run is collapsed.
        pid = uuid.uuid4()
        out = deidentify("Jane Doe attended a consultation.", pid, ["Jane", "Doe"])
        assert out == f"[patient:{pid}] attended a consultation."

    def test_collapses_runs_longer_than_two(self):
        pid = uuid.uuid4()
        out = deidentify("Mary Jane Doe arrived.", pid, ["Mary", "Jane", "Doe"])
        assert out == f"[patient:{pid}] arrived."

    def test_does_not_merge_tokens_separated_by_other_words(self):
        pid = uuid.uuid4()
        out = deidentify("Jane called; Doe confirmed.", pid, ["Jane", "Doe"])
        assert out == f"[patient:{pid}] called; [patient:{pid}] confirmed."

    def test_leaves_unrelated_words_alone(self):
        pid = uuid.uuid4()
        out = deidentify("The patient reported pain.", pid, ["Jane"])
        assert out == "The patient reported pain."


class TestEmbedder:
    def test_vectors_are_unit_length_and_correct_width(self):
        [vec] = HashingEmbedder().embed(["post-operative follow-up"])
        assert len(vec) == EMBEDDING_DIMENSIONS
        assert abs(sum(v * v for v in vec) - 1.0) < 1e-6

    def test_is_deterministic(self):
        a = HashingEmbedder().embed(["annual physical"])
        b = HashingEmbedder().embed(["annual physical"])
        assert a == b


class TestProtocolRetrieval:
    async def test_ingest_is_idempotent(self, session: AsyncSession):
        first = await ingest_protocol_dir(session)
        count_after_first = (
            await session.execute(select(func.count()).select_from(ProtocolChunk))
        ).scalar_one()

        await ingest_protocol_dir(session)
        count_after_second = (
            await session.execute(select(func.count()).select_from(ProtocolChunk))
        ).scalar_one()

        assert sum(first.values()) > 0
        assert count_after_first == count_after_second

    async def test_search_returns_ranked_passages_with_citations(self, session: AsyncSession):
        await ingest_protocol_dir(session)
        passages = await retrieval.search_protocols(session, "post-operative follow-up window", k=3)

        assert len(passages) == 3
        assert passages[0].score >= passages[-1].score
        assert all(p.source.endswith(".md") for p in passages)
        assert all(p.title for p in passages)

    async def test_k_bounds_the_result_count(self, session: AsyncSession):
        await ingest_protocol_dir(session)
        assert len(await retrieval.search_protocols(session, "waitlist", k=2)) == 2


class TestPatientRetrievalIsolation:
    """The property that matters: similarity must never bridge two patients."""

    async def _seed_two_patients(self, session: AsyncSession):
        alice, bob = uuid.uuid4(), uuid.uuid4()
        await ingest_patient_document(
            session,
            alice,
            source_doc_id="doc-alice-1",
            doc_type="visit_summary",
            deidentified_text="# Visit\n\nPost-operative check. Wound healing well.",
        )
        await ingest_patient_document(
            session,
            bob,
            source_doc_id="doc-bob-1",
            doc_type="visit_summary",
            deidentified_text="# Visit\n\nPost-operative check. Wound healing well.",
        )
        return alice, bob

    async def test_identical_documents_do_not_cross_patients(self, session: AsyncSession):
        alice, bob = await self._seed_two_patients(session)

        passages = await retrieval.search_patient_documents(
            session, patient_uuid=alice, query="wound healing", accessed_by=uuid.uuid4(), k=10
        )
        assert passages
        assert all(p.source == "doc-alice-1" for p in passages)

        stored = (
            (
                await session.execute(
                    select(PatientDocumentChunk).where(PatientDocumentChunk.patient_uuid == bob)
                )
            )
            .scalars()
            .all()
        )
        assert len(stored) == 1

    async def test_unknown_patient_returns_nothing(self, session: AsyncSession):
        await self._seed_two_patients(session)
        passages = await retrieval.search_patient_documents(
            session, patient_uuid=uuid.uuid4(), query="wound healing", accessed_by=uuid.uuid4(), k=5
        )
        assert passages == []


class TestPatientRetrievalIsAudited:
    async def test_retrieval_writes_an_access_log_row(self, session: AsyncSession):
        patient = uuid.uuid4()
        staff = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "doc-1", "visit_summary", "# Visit\n\nRoutine follow-up."
        )

        await retrieval.search_patient_documents(
            session, patient_uuid=patient, query="follow-up", accessed_by=staff, k=3
        )

        logs = (
            (
                await session.execute(
                    select(IdentityAccessLog).where(IdentityAccessLog.patient_uuid == patient)
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        assert logs[0].action == retrieval.RAG_RETRIEVAL_ACTION
        assert logs[0].accessed_by == staff

    async def test_empty_result_is_still_audited(self, session: AsyncSession):
        """An attempted lookup is as auditable as a successful one."""
        patient = uuid.uuid4()
        await retrieval.search_patient_documents(
            session, patient_uuid=patient, query="anything", accessed_by=uuid.uuid4(), k=3
        )
        count = (
            await session.execute(
                select(func.count())
                .select_from(IdentityAccessLog)
                .where(IdentityAccessLog.patient_uuid == patient)
            )
        ).scalar_one()
        assert count == 1


class TestRagEndpoints:
    async def test_protocol_search_requires_auth(self, client: AsyncClient):
        assert (
            await client.get("/rag/protocols/search", params={"q": "waitlist"})
        ).status_code in (
            401,
            403,
        )

    async def test_protocol_search_returns_passages(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        await ingest_protocol_dir(session)
        resp = await client.get(
            "/rag/protocols/search",
            params={"q": "how long is an offer held", "k": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "how long is an offer held"
        assert len(body["passages"]) == 3
        assert all("source" in p for p in body["passages"])

    async def test_patient_context_rejects_front_desk(
        self, client: AsyncClient, session: AsyncSession
    ):
        from app.auth.router import hash_password

        session.add(
            StaffUser(
                id=uuid.uuid4(),
                username="frontdesk",
                hashed_password=hash_password("pw"),
                role=StaffRole.front_desk,
            )
        )
        await session.commit()
        token = (
            await client.post("/auth/login", json={"username": "frontdesk", "password": "pw"})
        ).json()["access_token"]

        resp = await client.get(
            f"/rag/patients/{uuid.uuid4()}/context",
            params={"q": "follow-up"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_patient_context_response_carries_no_names(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        patient = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "doc-1", "visit_summary", "# Visit\n\nRoutine follow-up scheduled."
        )
        resp = await client.get(
            f"/rag/patients/{patient}/context",
            params={"q": "follow-up"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["patient_uuid"] == str(patient)
        assert body["audit_logged"] is True
        forbidden = {"first_name", "last_name", "dob", "phone", "email"}
        assert forbidden.isdisjoint(body.keys())
