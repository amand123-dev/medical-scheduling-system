"""
Generation layer tests.

The properties that matter here are not answer quality — that is what
evals/ measures. They are the guardrails around the patient path: it must
stay off unless deliberately enabled, it must log that text was sent to an
external model separately from an ordinary chart read, and the whole feature
must degrade to plain retrieval when no API key is configured.

A stub client stands in for Anthropic throughout, so the suite never needs a
key or a network call.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.identity.models import IdentityAccessLog
from app.rag import generation, retrieval
from app.rag.embeddings import HashingEmbedder
from app.rag.ingest import ingest_patient_document, ingest_protocol_dir
from app.rag.retrieval import Passage
from app.scheduling.models import StaffRole, StaffUser


@pytest.fixture(autouse=True)
def offline_embedder(monkeypatch):
    import app.rag.ingest as ingest_mod

    for module in (retrieval, ingest_mod):
        monkeypatch.setattr(module, "get_embedder", lambda *a, **k: HashingEmbedder())


class StubClient:
    """Records what it was asked, returns a canned answer."""

    def __init__(self, reply: str = "Offers are held for 30 minutes [1]."):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self.reply


@pytest.fixture
def stub(monkeypatch) -> StubClient:
    """Install a stub as the configured client, with a key present."""
    client = StubClient()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(generation, "get_client", lambda: client)
    return client


@pytest.fixture
def patient_generation_on(monkeypatch):
    monkeypatch.setattr(settings, "patient_generation_enabled", True)


def _passages(n: int = 2) -> list[Passage]:
    return [
        Passage(
            content=f"Body of passage {i}.",
            source=f"doc-{i}.md",
            title=f"Doc {i}",
            chunk_index=0,
            score=0.9 - i / 10,
        )
        for i in range(n)
    ]


class TestPromptGrounding:
    def test_prompt_numbers_passages_for_citation(self):
        prompt = generation.build_prompt("how long?", _passages(3))
        assert "[1]" in prompt and "[2]" in prompt and "[3]" in prompt
        assert "Question: how long?" in prompt

    def test_prompt_carries_every_passage_body(self):
        passages = _passages(4)
        prompt = generation.build_prompt("q", passages)
        for p in passages:
            assert p.content in prompt

    def test_system_prompt_forbids_outside_knowledge(self):
        assert "ONLY" in generation.GROUNDED_SYSTEM
        assert "do not answer" in generation.GROUNDED_SYSTEM.lower() or (
            "say so" in generation.GROUNDED_SYSTEM.lower()
        )

    def test_patient_system_prompt_bars_inference_about_the_person(self):
        """Computed signals drive support, not judgement — the prompt must say so."""
        lowered = generation.PATIENT_SYSTEM.lower()
        assert "the patient" in lowered
        assert "do not infer" in lowered

    async def test_empty_passages_never_reach_the_model(self, stub: StubClient):
        """
        An empty passage list would leave the model free to answer from its own
        knowledge, which is the failure mode grounding exists to prevent.
        """
        result = await generation.answer("anything", [], client=stub)
        assert result == generation.NO_PASSAGES
        assert stub.calls == []


class TestDegradesWithoutAKey:
    async def test_answer_is_none_when_no_client(self, monkeypatch):
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        assert await generation.answer("q", _passages(), client=None) is None

    async def test_protocol_ask_still_returns_passages(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        await ingest_protocol_dir(session)
        resp = await client.post(
            "/rag/protocols/ask",
            json={"q": "how long is an offer held", "k": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["generated"] is False
        assert body["answer"] is None
        assert len(body["passages"]) == 3, "retrieval must survive generation being unavailable"


class TestProtocolAsk:
    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.post("/rag/protocols/ask", json={"q": "waitlist"})
        assert resp.status_code in (401, 403)

    async def test_returns_answer_with_its_sources(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession, stub: StubClient
    ):
        await ingest_protocol_dir(session)
        resp = await client.post(
            "/rag/protocols/ask", json={"q": "how long is an offer held"}, headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == stub.reply
        assert body["generated"] is True
        assert body["passages"], "the answer must ship with the passages it came from"

    async def test_front_desk_may_ask_protocol_questions(
        self, client: AsyncClient, session: AsyncSession, stub: StubClient
    ):
        """Protocol docs carry no PHI, so every staff role gets this one."""
        from app.auth.router import hash_password

        session.add(
            StaffUser(
                id=uuid.uuid4(),
                username="fd2",
                hashed_password=hash_password("pw"),
                role=StaffRole.front_desk,
            )
        )
        await session.commit()
        await ingest_protocol_dir(session)
        token = (
            await client.post("/auth/login", json={"username": "fd2", "password": "pw"})
        ).json()["access_token"]
        resp = await client.post(
            "/rag/protocols/ask",
            json={"q": "waitlist offer"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestPatientAskIsOffByDefault:
    async def test_disabled_by_default_in_config(self):
        """
        The default must be off. Patient passages remain PHI after
        de-identification, so enabling this is a decision someone makes under a
        BAA — never something that ships switched on.
        """
        assert settings.patient_generation_enabled is False

    async def test_returns_403_while_disabled(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession, stub: StubClient
    ):
        patient = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "d1", "visit_summary", "# Visit\n\nRoutine follow-up."
        )
        resp = await client.post(
            f"/rag/patients/{patient}/ask", json={"q": "follow-up"}, headers=auth_headers
        )
        assert resp.status_code == 403

    async def test_nothing_is_sent_to_the_model_while_disabled(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession, stub: StubClient
    ):
        """The 403 must come before retrieval, not after the text was already sent."""
        patient = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "d1", "visit_summary", "# Visit\n\nRoutine follow-up."
        )
        await client.post(
            f"/rag/patients/{patient}/ask", json={"q": "follow-up"}, headers=auth_headers
        )
        assert stub.calls == [], "passages reached the model despite the feature being disabled"


class TestPatientAskWhenEnabled:
    async def test_rejects_front_desk(
        self, client: AsyncClient, session: AsyncSession, stub: StubClient, patient_generation_on
    ):
        from app.auth.router import hash_password

        session.add(
            StaffUser(
                id=uuid.uuid4(),
                username="fd3",
                hashed_password=hash_password("pw"),
                role=StaffRole.front_desk,
            )
        )
        await session.commit()
        token = (
            await client.post("/auth/login", json={"username": "fd3", "password": "pw"})
        ).json()["access_token"]
        resp = await client.post(
            f"/rag/patients/{uuid.uuid4()}/ask",
            json={"q": "follow-up"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_answers_and_reports_that_text_left_the_system(
        self,
        client: AsyncClient,
        auth_headers: dict,
        session: AsyncSession,
        stub: StubClient,
        patient_generation_on,
    ):
        patient = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "d1", "visit_summary", "# Visit\n\nRoutine follow-up scheduled."
        )
        resp = await client.post(
            f"/rag/patients/{patient}/ask", json={"q": "follow-up"}, headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == stub.reply
        assert body["sent_to_external_model"] is True, (
            "the UI must be able to state this, not guess"
        )
        assert body["audit_logged"] is True

    async def test_response_carries_no_names(
        self,
        client: AsyncClient,
        auth_headers: dict,
        session: AsyncSession,
        stub: StubClient,
        patient_generation_on,
    ):
        patient = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "d1", "visit_summary", "# Visit\n\nRoutine follow-up."
        )
        body = (
            await client.post(
                f"/rag/patients/{patient}/ask", json={"q": "follow-up"}, headers=auth_headers
            )
        ).json()
        assert body["patient_uuid"] == str(patient)
        assert {"first_name", "last_name", "dob", "phone", "email"}.isdisjoint(body.keys())

    async def test_generation_writes_its_own_audit_action(
        self,
        client: AsyncClient,
        auth_headers: dict,
        session: AsyncSession,
        stub: StubClient,
        patient_generation_on,
    ):
        """
        Reading a chart and shipping it to a third party are different events.
        An audit trail that cannot tell them apart is not much of an audit trail.
        """
        patient = uuid.uuid4()
        await ingest_patient_document(
            session, patient, "d1", "visit_summary", "# Visit\n\nRoutine follow-up."
        )
        await client.post(
            f"/rag/patients/{patient}/ask", json={"q": "follow-up"}, headers=auth_headers
        )
        actions = (
            (
                await session.execute(
                    select(IdentityAccessLog.action).where(
                        IdentityAccessLog.patient_uuid == patient
                    )
                )
            )
            .scalars()
            .all()
        )
        assert retrieval.RAG_GENERATION_ACTION in actions
        assert retrieval.RAG_RETRIEVAL_ACTION in actions

    async def test_no_passages_means_nothing_was_sent(
        self,
        client: AsyncClient,
        auth_headers: dict,
        session: AsyncSession,
        stub: StubClient,
        patient_generation_on,
    ):
        """A patient with no documents must not be logged as having been sent out."""
        body = (
            await client.post(
                f"/rag/patients/{uuid.uuid4()}/ask",
                json={"q": "follow-up"},
                headers=auth_headers,
            )
        ).json()
        assert body["sent_to_external_model"] is False
        assert body["passages"] == []

    async def test_only_that_patients_passages_are_sent(
        self,
        client: AsyncClient,
        auth_headers: dict,
        session: AsyncSession,
        stub: StubClient,
        patient_generation_on,
    ):
        """The prompt is the last place a cross-patient leak could hide."""
        a, b = uuid.uuid4(), uuid.uuid4()
        await ingest_patient_document(
            session, a, "a1", "visit_summary", "# Visit\n\nPatient A ankle sprain follow-up."
        )
        await ingest_patient_document(
            session, b, "b1", "visit_summary", "# Visit\n\nPatient B ankle sprain follow-up."
        )
        await client.post(f"/rag/patients/{a}/ask", json={"q": "ankle"}, headers=auth_headers)
        assert len(stub.calls) == 1
        _system, prompt = stub.calls[0]
        assert "Patient A" in prompt
        assert "Patient B" not in prompt
