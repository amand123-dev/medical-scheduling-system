CLAUDE.md
# Project Overview
SmallPractice Scheduler — a lightweight appointment scheduling web app for solo and small (1–5 provider) medical practices, the segment priced out of enterprise tools (Epic, athenahealth) by cost and complexity.
Two differentiating features sit on top of a simple, self-serve scheduler:

Intelligent waitlist — auto-fills cancelled slots by matching them to prioritized waiting patients.
No-show-aware reminders — a computed risk score that escalates outreach (support, not punishment).

This is a portfolio project on synthetic data only. Prioritize a coherent, deployed slice over breadth.
Tech Stack

Frontend: React + Tailwind + FullCalendar
Backend: Python + FastAPI
DB: PostgreSQL — two schemas, identity and operational
ML: scikit-learn (no-show model behind an internal endpoint)
Auth: JWT with role-based permissions
Deploy: Render/Railway/Fly + managed Postgres

# About Me
I am a masters student with a background in healthcare looking to build this as a portfolio project

# Commands
bash# Backend
uvicorn app.main:app --reload        # run API locally
pytest                               # run tests (before every commit)
ruff check --fix && ruff format      # lint + format

# Frontend
npm run dev                          # run frontend
npm run build                        # production build
npm run typecheck                    # typecheck

# Data
python scripts/seed_synthetic.py     # generate fake patients/appointments via Faker
Project Structure
backend/app/        FastAPI app (scheduling engine, matcher, scorer, identity service)
backend/scripts/    synthetic data seeding
frontend/src/       React UI (calendar, booking, waitlist, settings)
docs/               build plan, design notes
Architecture

Identity is separated from operations (tokenization). Real PII lives in identity.patient_identity, keyed by a random UUIDv4 (never derived from PII). Operational tables reference only the UUID and never store a name. UUID → name resolution is a separate, permissioned, audit-logged operation.
The engine does the busywork. Slot length is derived from visit type. Cancellations trigger automatic backfill. Reminders escalate from the risk score.

Data Model
identity schema (encrypted, locked down):

patient_identity(patient_uuid PK, first_name, last_name, dob, phone, email, created_at) — PII fields encrypted
identity_access_log(id PK, patient_uuid, accessed_by, action, at)

operational schema (UUID-keyed, no names ever):

provider, visit_type(duration_minutes, is_new_patient), appointment(status, start/end_time), waitlist_entry(priority, requested_at, window, status), staff_user(role)

Conventions

Operational schema, logs, and API responses contain UUIDs only — never PII.
Any identity-resolving endpoint must check role AND write to identity_access_log.
Make thresholds configurable, not hard-coded (slot lengths, risk thresholds, matcher weights) — clinics vary.
Slot length comes from visit_type.duration_minutes; never hand-enter durations.
Run pytest and ruff before every commit.

Hard Constraints (do not violate — flag instead)

Never write "HIPAA compliant" — use "HIPAA-aware." A reversible code is still PHI; this is data-minimization, not de-identification.
Synthetic data only. Never use real PII. Train the no-show model on the public Kaggle no-show dataset.
No clinical surveillance. Do not build opioid/controlled-substance tracking, patient flagging, or "doctor-shopping" detection. The only acceptable medication-adjacent feature is protocol-driven follow-up scheduling ("this visit type needs a follow-up within N days").
Computed signals drive support, not punishment — reminders and care coordination, never deprioritization.
No real SMS/email. Simulate sends by logging to a table.

Build Order (finish each phase before the next)

MVP scheduler — two-schema model, providers, visit types, book/cancel/complete, calendar, role-based auth, audited reverse-lookup. Complete project on its own.
Waitlist backfill (headline) — matcher: filter by fit + provider + window, score by w1*priority + w2*wait_time − w3*decline_risk, offer with a time-limited hold, cascade on expire. Weights configurable.
No-show intelligence — v1 ratio score (no_shows/total_booked, min 3 prior appts) → wire risk buckets into reminder escalation. v2 optional: scikit-learn model.
Polish — color + icon/label legend (never color alone), self-serve settings page, dashboard (fill rate, no-show rate, slots recovered).

A deployed Phase 1–2 beats a half-built Phase 1–4.
Out of Scope (note as future work, do not build)
Real insurance eligibility, real EHR integration, real SMS/email delivery, i18n, any clinical/prescription surveillance.
References

docs/scheduler-build-plan.md — full reasoning, data model detail, resume framing