import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling import crud
from app.scheduling.models import Provider, VisitType
from app.scheduling.schemas import ProviderCreate, VisitTypeCreate


async def _make_provider(session: AsyncSession) -> Provider:
    return await crud.create_provider(session, ProviderCreate(name="Dr. Test", specialty="GP"))


async def _make_visit_type(session: AsyncSession, minutes: int = 30) -> VisitType:
    return await crud.create_visit_type(
        session, VisitTypeCreate(name="Follow-up", duration_minutes=minutes)
    )


class TestProviders:
    async def test_list_providers_requires_auth(self, client: AsyncClient):
        resp = await client.get("/providers")
        assert resp.status_code == 403

    async def test_create_and_list_provider(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/providers",
            json={"name": "Dr. Smith", "specialty": "Family"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Dr. Smith"
        assert "id" in data

        list_resp = await client.get("/providers", headers=auth_headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1


class TestAppointments:
    async def test_book_appointment_derives_end_time(
        self, session: AsyncSession, client: AsyncClient, auth_headers: dict
    ):
        provider = await _make_provider(session)
        vt = await _make_visit_type(session, minutes=45)
        patient_uuid = str(uuid.uuid4())
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        resp = await client.post(
            "/appointments",
            json={
                "provider_id": str(provider.id),
                "patient_uuid": patient_uuid,
                "visit_type_id": str(vt.id),
                "start_time": start.isoformat(),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        end = datetime.fromisoformat(data["end_time"])
        start_parsed = datetime.fromisoformat(data["start_time"])
        delta = end - start_parsed
        assert delta == timedelta(minutes=45)

    async def test_overlap_rejected(
        self, session: AsyncSession, client: AsyncClient, auth_headers: dict
    ):
        provider = await _make_provider(session)
        vt = await _make_visit_type(session, minutes=30)
        patient_uuid = str(uuid.uuid4())
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        payload = {
            "provider_id": str(provider.id),
            "patient_uuid": patient_uuid,
            "visit_type_id": str(vt.id),
            "start_time": start.isoformat(),
        }
        r1 = await client.post("/appointments", json=payload, headers=auth_headers)
        assert r1.status_code == 201

        r2 = await client.post("/appointments", json=payload, headers=auth_headers)
        assert r2.status_code == 409

    async def test_cancel_appointment(
        self, session: AsyncSession, client: AsyncClient, auth_headers: dict
    ):
        provider = await _make_provider(session)
        vt = await _make_visit_type(session)
        patient_uuid = str(uuid.uuid4())
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        create_resp = await client.post(
            "/appointments",
            json={
                "provider_id": str(provider.id),
                "patient_uuid": patient_uuid,
                "visit_type_id": str(vt.id),
                "start_time": start.isoformat(),
            },
            headers=auth_headers,
        )
        appt_id = create_resp.json()["id"]

        cancel_resp = await client.patch(f"/appointments/{appt_id}/cancel", headers=auth_headers)
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    async def test_no_pii_in_appointment_response(
        self, session: AsyncSession, client: AsyncClient, auth_headers: dict
    ):
        provider = await _make_provider(session)
        vt = await _make_visit_type(session)
        patient_uuid = str(uuid.uuid4())
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        resp = await client.post(
            "/appointments",
            json={
                "provider_id": str(provider.id),
                "patient_uuid": patient_uuid,
                "visit_type_id": str(vt.id),
                "start_time": start.isoformat(),
            },
            headers=auth_headers,
        )
        data = resp.json()
        forbidden = {"first_name", "last_name", "dob", "phone", "email"}
        assert forbidden.isdisjoint(data.keys()), f"PII leaked in response: {data.keys()}"

    async def test_reminders_created_on_booking(
        self, session: AsyncSession, client: AsyncClient, auth_headers: dict
    ):
        provider = await _make_provider(session)
        vt = await _make_visit_type(session)
        patient_uuid = str(uuid.uuid4())
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)

        create_resp = await client.post(
            "/appointments",
            json={
                "provider_id": str(provider.id),
                "patient_uuid": patient_uuid,
                "visit_type_id": str(vt.id),
                "start_time": start.isoformat(),
            },
            headers=auth_headers,
        )
        appt_id = create_resp.json()["id"]

        reminder_resp = await client.get(f"/appointments/{appt_id}/reminders", headers=auth_headers)
        assert reminder_resp.status_code == 200
        assert len(reminder_resp.json()) >= 1


class TestNoShowRisk:
    async def test_insufficient_data_bucket(
        self, session: AsyncSession, client: AsyncClient, auth_headers: dict
    ):
        patient_uuid = str(uuid.uuid4())
        resp = await client.get(f"/scorer/risk/{patient_uuid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["bucket"] == "insufficient_data"

    async def test_risk_score_computed(self, session: AsyncSession):
        provider = await _make_provider(session)
        vt = await _make_visit_type(session)
        patient_uuid = uuid.uuid4()
        start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        from app.scheduling.models import Appointment, AppointmentStatus

        for i, status in enumerate(
            [
                AppointmentStatus.completed,
                AppointmentStatus.no_show,
                AppointmentStatus.no_show,
            ]
        ):
            appt = Appointment(
                id=uuid.uuid4(),
                provider_id=provider.id,
                patient_uuid=patient_uuid,
                visit_type_id=vt.id,
                start_time=start - timedelta(days=i + 1),
                end_time=start - timedelta(days=i + 1) + timedelta(minutes=30),
                status=status,
            )
            session.add(appt)
        await session.commit()

        risk = await crud.compute_no_show_risk(session, patient_uuid)
        assert risk is not None
        assert abs(risk - 2 / 3) < 0.01
