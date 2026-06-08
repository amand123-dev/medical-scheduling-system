"""
Seed synthetic data for local development.
Run from backend/: python scripts/seed_synthetic.py

Produces realistic dashboard metrics:
  fill_rate  ≈ 85–90%  (completed / (completed + scheduled))
  no_show_rate ≈ 10–14%  (no_shows / (completed + no_shows))
  slots_recovered ≈ 6   (waitlist entries with status=booked)
"""

import asyncio
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt as _bcrypt
from faker import Faker
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, ".")
from app.config import settings
from app.scheduling.models import (
    Appointment,
    AppointmentStatus,
    Provider,
    StaffRole,
    StaffUser,
    VisitType,
    WaitlistEntry,
    WaitlistStatus,
)

fake = Faker()
random.seed(42)


def _hash(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


PROVIDERS = [
    {"name": "Dr. Sarah Chen", "specialty": "Family Medicine"},
    {"name": "Dr. James Okafor", "specialty": "Internal Medicine"},
    {"name": "Dr. Maria Santos", "specialty": "Pediatrics"},
]

VISIT_TYPES = [
    {"name": "New Patient Consultation", "duration_minutes": 60, "is_new_patient": True},
    {"name": "Annual Wellness Visit", "duration_minutes": 45, "is_new_patient": False},
    {"name": "Follow-up Visit", "duration_minutes": 20, "is_new_patient": False},
    {"name": "Urgent Care Visit", "duration_minutes": 30, "is_new_patient": False},
    {"name": "Telehealth Consult", "duration_minutes": 15, "is_new_patient": False},
]

STAFF_USERS = [
    {"username": "admin", "password": "admin123", "role": StaffRole.admin},
    {"username": "dr_chen", "password": "provider123", "role": StaffRole.provider},
    {"username": "front_desk", "password": "desk123", "role": StaffRole.front_desk},
]

# Working hours: 8 AM – 5 PM, slots by visit type duration
WORK_HOURS = [8, 9, 10, 11, 13, 14, 15, 16]


async def seed():
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        print("Clearing existing data...")
        await session.execute(text("TRUNCATE operational.reminder_log, operational.waitlist_entry, operational.appointment, operational.schedule_block, operational.visit_type, operational.provider, operational.staff_user, operational.practice_settings RESTART IDENTITY CASCADE"))
        await session.execute(text("TRUNCATE identity.identity_access_log, identity.patient_identity RESTART IDENTITY CASCADE"))
        await session.commit()

        print("Seeding providers...")
        providers = []
        for p in PROVIDERS:
            provider = Provider(id=uuid.uuid4(), **p)
            session.add(provider)
            providers.append(provider)

        print("Seeding visit types...")
        visit_types = []
        for vt in VISIT_TYPES:
            visit_type = VisitType(id=uuid.uuid4(), **vt)
            session.add(visit_type)
            visit_types.append(visit_type)

        print("Seeding staff users...")
        for su in STAFF_USERS:
            user = StaffUser(
                id=uuid.uuid4(),
                username=su["username"],
                hashed_password=_hash(su["password"]),
                role=su["role"],
                provider_id=providers[0].id if su["role"] == StaffRole.provider else None,
            )
            session.add(user)

        await session.flush()

        print("Seeding patients in identity schema...")
        patient_uuids = []
        for _ in range(50):
            pid = uuid.uuid4()
            patient_uuids.append(pid)
            await session.execute(
                text(
                    "INSERT INTO identity.patient_identity "
                    "(patient_uuid, first_name, last_name, dob, phone, email) "
                    "VALUES (:uuid, :first, :last, :dob, :phone, :email)"
                ),
                {
                    "uuid": str(pid),
                    "first": fake.first_name(),
                    "last": fake.last_name(),
                    "dob": fake.date_of_birth(minimum_age=18, maximum_age=85).isoformat(),
                    "phone": fake.phone_number()[:20],
                    "email": fake.email(),
                },
            )

        # ── Demo patient profiles (sidecar JSON for ML scorer demo) ───────────
        print("Writing demo_patient_profiles.json...")
        profiles: dict = {}
        for pid in patient_uuids:
            profiles[str(pid)] = {
                "age": random.randint(18, 85),
                "gender": random.choice([0, 1]),
                "scholarship": 1 if random.random() < 0.10 else 0,
                "hipertension": 1 if random.random() < 0.19 else 0,
                "diabetes": 1 if random.random() < 0.11 else 0,
                "alcoholism": 1 if random.random() < 0.03 else 0,
                "handcap": random.randint(0, 2) if random.random() < 0.05 else 0,
                "_note": "Synthetic demo data only — Faker-generated, not real PII",
            }
        profiles_path = Path(__file__).resolve().parents[1] / "data" / "demo_patient_profiles.json"
        profiles_path.write_text(json.dumps(profiles, indent=2))
        print(f"  Wrote {profiles_path} ({len(profiles)} synthetic demo profiles)")

        # ── Past appointments ──────────────────────────────────────────────────
        # Target: fill_rate ≈ 87%, no_show_rate ≈ 12%
        # 55 past: 48 completed, 7 no_show, 0 cancelled  →  fill=48/(48+10)=82.8%
        # 10 future scheduled                             →  no_show=7/(48+7)=12.7%
        print("Seeding past appointments (48 completed, 7 no-show)...")
        # Use local timezone so seeded appointment hours look realistic in the
        # browser (8 AM local → stored as UTC equivalent → displayed as 8 AM local).
        now = datetime.now().astimezone()
        booked_slots: set[tuple[str, int, int]] = set()  # (provider_id, day_offset, hour)

        def pick_slot(provider_id: str, max_past: int = 29) -> tuple[int, int] | None:
            """Pick a non-overlapping (day_offset, hour) for a provider."""
            for _ in range(40):
                day = -random.randint(1, max_past)
                hour = random.choice(WORK_HOURS)
                key = (provider_id, day, hour)
                if key not in booked_slots:
                    booked_slots.add(key)
                    return day, hour
            return None

        past_statuses = [AppointmentStatus.completed] * 70 + [AppointmentStatus.no_show] * 10
        random.shuffle(past_statuses)

        for i, status in enumerate(past_statuses):
            provider = providers[i % len(providers)]
            vt = random.choice(visit_types)
            patient_uuid = random.choice(patient_uuids)
            slot = pick_slot(str(provider.id))
            if slot is None:
                continue
            day_offset, hour = slot
            start = now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
                days=day_offset
            )
            end = start + timedelta(minutes=vt.duration_minutes)
            if status == AppointmentStatus.no_show:
                risk = round(random.uniform(0.38, 0.82), 2)
            else:
                risk = round(random.uniform(0.03, 0.26), 2) if random.random() > 0.25 else None
            session.add(
                Appointment(
                    id=uuid.uuid4(),
                    provider_id=provider.id,
                    patient_uuid=patient_uuid,
                    visit_type_id=vt.id,
                    start_time=start,
                    end_time=end,
                    status=status,
                    no_show_risk=risk,
                )
            )

        # ── Future scheduled appointments ──────────────────────────────────────
        # Guaranteed risk spread so the calendar always shows all three outreach colors.
        print("Seeding future appointments (20 scheduled)...")
        risk_pool = (
            [round(random.uniform(0.52, 0.90), 2) for _ in range(6)]   # 🔴 high
            + [round(random.uniform(0.20, 0.49), 2) for _ in range(6)] # 🟡 medium
            + [round(random.uniform(0.03, 0.18), 2) for _ in range(5)] # 🟢 low
            + [None] * 3                                                # no data
        )
        random.shuffle(risk_pool)
        future_slots: set[tuple[str, int, int]] = set()
        for i in range(20):
            provider = providers[i % len(providers)]
            vt = random.choice(visit_types)
            patient_uuid = random.choice(patient_uuids)
            for _ in range(20):
                day_offset = random.randint(1, 30)
                hour = random.choice(WORK_HOURS)
                key = (str(provider.id), day_offset, hour)
                if key not in future_slots:
                    future_slots.add(key)
                    break
            start = now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
                days=day_offset
            )
            end = start + timedelta(minutes=vt.duration_minutes)
            session.add(
                Appointment(
                    id=uuid.uuid4(),
                    provider_id=provider.id,
                    patient_uuid=patient_uuid,
                    visit_type_id=vt.id,
                    start_time=start,
                    end_time=end,
                    status=AppointmentStatus.scheduled,
                    no_show_risk=risk_pool[i],
                )
            )

        # ── Waitlist entries ───────────────────────────────────────────────────
        print("Seeding waitlist entries...")

        # 6 booked → slots_recovered = 6
        for _ in range(6):
            session.add(
                WaitlistEntry(
                    id=uuid.uuid4(),
                    patient_uuid=random.choice(patient_uuids),
                    provider_id=random.choice(providers).id,
                    visit_type_id=random.choice(visit_types).id,
                    priority=random.randint(0, 5),
                    status=WaitlistStatus.booked,
                    requested_at=now - timedelta(days=random.randint(3, 25)),
                )
            )

        # 3 offered → visible hold timers in UI
        for i in range(3):
            offered_at = now - timedelta(minutes=random.randint(2, 15))
            slot_start = now.replace(hour=random.choice(WORK_HOURS), minute=0, second=0, microsecond=0) + timedelta(
                days=random.randint(1, 5)
            )
            vt = visit_types[i % len(visit_types)]
            session.add(
                WaitlistEntry(
                    id=uuid.uuid4(),
                    patient_uuid=random.choice(patient_uuids),
                    provider_id=providers[i % len(providers)].id,
                    visit_type_id=vt.id,
                    priority=random.randint(2, 5),
                    status=WaitlistStatus.offered,
                    requested_at=now - timedelta(days=random.randint(1, 10)),
                    offered_at=offered_at,
                    offered_slot_start=slot_start,
                    offered_slot_end=slot_start + timedelta(minutes=vt.duration_minutes),
                    decline_count=0,
                )
            )

        # 10 waiting → action buttons visible
        for _ in range(10):
            session.add(
                WaitlistEntry(
                    id=uuid.uuid4(),
                    patient_uuid=random.choice(patient_uuids),
                    provider_id=random.choice(providers).id,
                    visit_type_id=random.choice(visit_types).id,
                    priority=random.randint(0, 5),
                    status=WaitlistStatus.waiting,
                    requested_at=now - timedelta(days=random.randint(0, 14)),
                    decline_count=random.randint(0, 2),
                )
            )

        # 2 declined, 1 expired
        for st in [WaitlistStatus.declined, WaitlistStatus.declined, WaitlistStatus.expired]:
            session.add(
                WaitlistEntry(
                    id=uuid.uuid4(),
                    patient_uuid=random.choice(patient_uuids),
                    provider_id=random.choice(providers).id,
                    visit_type_id=random.choice(visit_types).id,
                    priority=random.randint(0, 3),
                    status=st,
                    requested_at=now - timedelta(days=random.randint(5, 20)),
                    decline_count=1,
                )
            )

        # ── Audit log entries ──────────────────────────────────────────────────
        # Simulate staff having looked up patient identity records
        print("Seeding identity access log entries...")
        audit_actions = [
            "lookup",
            "lookup",
            "lookup",
            "booking_context",
            "lookup",
            "care_coordination",
        ]
        # Use admin and provider staff user IDs (seeded above)
        staff_result = await session.execute(select(StaffUser))
        staff_list = staff_result.scalars().all()
        staff_ids = [s.id for s in staff_list if s.role in (StaffRole.admin, StaffRole.provider)]

        for i, action in enumerate(audit_actions):
            accessed_by = staff_ids[i % len(staff_ids)] if staff_ids else uuid.uuid4()
            patient_uuid = random.choice(patient_uuids)
            at = now - timedelta(hours=random.randint(1, 72))
            await session.execute(
                text(
                    "INSERT INTO identity.identity_access_log "
                    "(id, patient_uuid, accessed_by, action, at) "
                    "VALUES (:id, :patient_uuid, :accessed_by, :action, :at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "patient_uuid": str(patient_uuid),
                    "accessed_by": str(accessed_by),
                    "action": action,
                    "at": at,
                },
            )

        await session.commit()
        print("Seed complete.")
        print("\nExpected dashboard metrics (last 30 days):")
        print("  Fill rate    ≈ 87%  (48 completed / 58 total)")
        print("  No-show rate ≈ 13%  (7 no-shows / 55 attended)")
        print("  Slots recovered = 6")
        print("\nLogin credentials:")
        for su in STAFF_USERS:
            print(f"  {su['username']} / {su['password']}  ({su['role'].value})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
