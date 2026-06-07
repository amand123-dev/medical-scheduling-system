import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import crud
from app.identity.models import IdentityAccessLog
from app.identity.schemas import PatientCreate


class TestIdentityAPI:
    async def test_create_patient_returns_uuid_only(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/identity/patients",
            json={
                "first_name": "Jane",
                "last_name": "Doe",
                "dob": "1990-01-01",
                "phone": "555-0100",
                "email": "jane@example.com",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "patient_uuid" in data
        assert "first_name" not in data
        assert "last_name" not in data

    async def test_get_patient_requires_elevated_role(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        patient = await crud.create_patient(
            session,
            PatientCreate(
                first_name="Test",
                last_name="Patient",
                dob="1980-05-15",
                phone="555-0101",
                email="tp@example.com",
            ),
        )
        resp = await client.get(
            f"/identity/patients/{patient.patient_uuid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "Test"

    async def test_access_log_written_on_lookup(
        self, client: AsyncClient, auth_headers: dict, session: AsyncSession
    ):
        patient = await crud.create_patient(
            session,
            PatientCreate(
                first_name="Audit",
                last_name="Trail",
                dob="1975-03-22",
                phone="555-0102",
                email="audit@example.com",
            ),
        )
        result = await session.execute(select(IdentityAccessLog))
        before_count = len(result.scalars().all())

        await client.get(
            f"/identity/patients/{patient.patient_uuid}",
            headers=auth_headers,
        )

        await session.refresh(patient)
        result2 = await session.execute(select(IdentityAccessLog))
        after_count = len(result2.scalars().all())
        assert after_count == before_count + 1

    async def test_unknown_patient_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get(
            f"/identity/patients/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_front_desk_cannot_access_identity(
        self, client: AsyncClient, session: AsyncSession
    ):
        from app.auth.router import hash_password
        from app.scheduling.models import StaffRole, StaffUser

        desk_user = StaffUser(
            id=uuid.uuid4(),
            username="deskuser",
            hashed_password=hash_password("deskpass"),
            role=StaffRole.front_desk,
        )
        session.add(desk_user)
        await session.commit()

        login_resp = await client.post(
            "/auth/login", json={"username": "deskuser", "password": "deskpass"}
        )
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        patient = await crud.create_patient(
            session,
            PatientCreate(
                first_name="Private",
                last_name="Person",
                dob="1985-07-04",
                phone="555-0199",
                email="private@example.com",
            ),
        )
        resp = await client.get(f"/identity/patients/{patient.patient_uuid}", headers=headers)
        assert resp.status_code == 403
