"""Refresh demo data on a running instance, over the HTTP API.

`seed_synthetic.py` needs direct database access. That is fine locally, but the
deployed instance keeps its DATABASE_URL in the platform's secret store, so
re-seeding a deployment means retrieving a production credential. This script
avoids that: it authenticates as a staff user and drives the same public API the
frontend uses, so the only credential involved is a login the operator already
has.

It is additive. Nothing is deleted, because the API exposes no delete. Stale
appointments simply fall outside the dashboard window and stop mattering.

What it builds, and why this shape:

Risk scores are NOT set directly -- the API does not accept them. POST
/appointments computes `no_show_risk` from the patient's own history via the
ratio scorer, which needs at least 3 resolved appointments before it will return
a number at all. So the script writes history first, in deliberate no-show
ratios, and only then books the upcoming appointments. The calendar's risk
colours therefore come out of the real scorer rather than being fabricated,
which is the more honest thing to demo.

Usage:
    python scripts/refresh_demo_data.py --api-url https://... --username admin
    python scripts/refresh_demo_data.py --dry-run          # plan only, no writes

Password is read from --password or the DEMO_PASSWORD environment variable.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

WORK_HOURS = (8, 9, 10, 11, 13, 14, 15, 16)

# Risk buckets come from settings: low < 0.2 <= medium < 0.5 <= high. Targets are
# placed mid-band, not on the boundary, so a patient does not slide into the
# neighbouring colour because of one extra appointment.
#   (label, patient count, target no-show ratio, appointments to add)
RISK_TIERS = (
    ("high", 3, 0.65, 6),
    ("medium", 4, 0.33, 6),
    ("low", 8, 0.05, 5),
)

TIMEOUT = 30.0

# Appointment status -> the PATCH endpoint that sets it.
STATUS_ENDPOINT = {"completed": "complete", "no_show": "no-show"}


@dataclass
class Plan:
    """What the script intends to write, before it writes any of it."""

    history: list[dict] = field(default_factory=list)
    upcoming: list[dict] = field(default_factory=list)
    waitlist: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        no_shows = sum(1 for a in self.history if a["status"] == "no_show")
        return (
            f"{len(self.history)} past appointments "
            f"({len(self.history) - no_shows} completed, {no_shows} no-show), "
            f"{len(self.upcoming)} upcoming, "
            f"{len(self.waitlist)} waitlist entries "
            f"({sum(1 for w in self.waitlist if w['backfill'])} to be backfilled)"
        )


class DemoRefresher:
    def __init__(self, api_url: str, token: str, dry_run: bool = False) -> None:
        self.api_url = api_url.rstrip("/")
        self.dry_run = dry_run
        self.client = httpx.Client(timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}"})
        self._taken: set[tuple[str, str]] = set()
        self.failures: list[str] = []

    # -- HTTP ---------------------------------------------------------------

    def get(self, path: str) -> object:
        resp = self.client.get(f"{self.api_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def _post_appointment(self, body: dict) -> str | None:
        resp = self.client.post(f"{self.api_url}/appointments", json=body)
        if resp.status_code == 201:
            return resp.json()["id"]
        # 409 overlap / blocked date is expected while probing slots; the caller
        # retries a different one. Anything else is worth surfacing.
        if resp.status_code not in (400, 409):
            self.failures.append(f"POST /appointments -> {resp.status_code}: {resp.text[:120]}")
        return None

    def patch_status(self, appt_id: str, status: str) -> bool:
        resp = self.client.patch(f"{self.api_url}/appointments/{appt_id}/{status}")
        if resp.status_code != 200:
            self.failures.append(f"PATCH /appointments/{appt_id}/{status} -> {resp.status_code}")
            return False
        return True

    def add_waitlist(self, body: dict) -> str | None:
        resp = self.client.post(f"{self.api_url}/waitlist", json=body)
        if resp.status_code == 201:
            return resp.json()["id"]
        self.failures.append(f"POST /waitlist -> {resp.status_code}: {resp.text[:120]}")
        return None

    def backfill(self, entry_id: str) -> bool:
        """Run one waitlist entry through the real offer -> accept path.

        This deliberately goes through the engine rather than writing a booked
        status directly, so "slots recovered" on the dashboard reflects the
        matcher actually having done the work.
        """
        offer = self.client.post(f"{self.api_url}/waitlist/{entry_id}/offer")
        if offer.status_code != 200:
            self.failures.append(f"offer {entry_id} -> {offer.status_code}: {offer.text[:100]}")
            return False
        accept = self.client.patch(f"{self.api_url}/waitlist/{entry_id}/accept")
        if accept.status_code != 200:
            self.failures.append(f"accept {entry_id} -> {accept.status_code}: {accept.text[:100]}")
            return False
        return True

    # -- slot allocation ----------------------------------------------------

    def _slot(self, provider_id: str, day_offset: int) -> datetime | None:
        """Find an unused hour on the given day for this provider.

        Only tracks what this run has claimed; genuine conflicts with existing
        data come back from the API as 409 and are retried by the caller.
        """
        base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        hours = list(WORK_HOURS)
        random.shuffle(hours)
        for hour in hours:
            when = (base + timedelta(days=day_offset)).replace(hour=hour)
            key = (provider_id, when.isoformat())
            if key not in self._taken:
                self._taken.add(key)
                return when
        return None

    def book(self, provider_id: str, patient_uuid: str, vt_id: str, day_offset: int) -> str | None:
        """Book one appointment, probing a few days for a free slot."""
        for drift in range(6):
            when = self._slot(provider_id, day_offset + drift * (1 if day_offset >= 0 else -1))
            if when is None:
                continue
            if self.dry_run:
                return "dry-run"
            appt_id = self._post_appointment(
                {
                    "provider_id": provider_id,
                    "patient_uuid": patient_uuid,
                    "visit_type_id": vt_id,
                    "start_time": when.isoformat(),
                }
            )
            if appt_id:
                return appt_id
        return None


def plan_additions(existing: tuple[int, int], target_ratio: float, to_add: int) -> tuple[int, int]:
    """How many no-shows and completions to add to reach a target ratio.

    The ratio scorer counts a patient's whole history, not a recent window, so
    appointments already on the instance move the result. Given the patient's
    existing (resolved_total, no_shows), solve for the split of `to_add` new
    appointments that lands the final ratio closest to target.

    Returns (n_no_show, n_completed).
    """
    total_before, no_shows_before = existing
    final_total = total_before + to_add
    wanted_no_shows = round(target_ratio * final_total) - no_shows_before
    n_no_show = max(0, min(to_add, wanted_no_shows))
    return n_no_show, to_add - n_no_show


def patient_history(appointments: list[dict]) -> dict[str, tuple[int, int]]:
    """Map patient_uuid -> (resolved appointments, no-shows) from existing data."""
    history: dict[str, tuple[int, int]] = {}
    for appt in appointments:
        status = appt.get("status")
        if status not in ("completed", "no_show"):
            continue
        total, no_shows = history.get(appt["patient_uuid"], (0, 0))
        history[appt["patient_uuid"]] = (total + 1, no_shows + (status == "no_show"))
    return history


def build_plan(
    patients: list[str],
    providers: list[str],
    visit_types: list[str],
    history: dict[str, tuple[int, int]],
) -> Plan:
    """Assign patients to risk tiers and lay out history, upcoming visits, waitlist."""
    plan = Plan()

    # Assign tiers by the history a patient already has, worst record first. A
    # patient with a heavy no-show history cannot be pulled down into the "low"
    # bucket by adding a handful of completions -- the scorer counts everything
    # -- so pushing such a patient into the low tier would silently produce the
    # wrong colour. Sorting first means each tier gets the patients it can
    # actually reach.
    def existing_ratio(patient: str) -> float:
        total, no_shows = history.get(patient, (0, 0))
        return no_shows / total if total else 0.0

    patients = sorted(patients, key=existing_ratio, reverse=True)

    cursor = 0
    for label, count, ratio, to_add in RISK_TIERS:
        for _ in range(count):
            if cursor >= len(patients):
                break
            patient = patients[cursor]
            cursor += 1
            existing = history.get(patient, (0, 0))
            n_no_show, n_completed = plan_additions(existing, ratio, to_add)
            statuses = ["no_show"] * n_no_show + ["completed"] * n_completed
            random.shuffle(statuses)
            for i, status in enumerate(statuses):
                plan.history.append(
                    {
                        "patient_uuid": patient,
                        "provider_id": providers[cursor % len(providers)],
                        "visit_type_id": random.choice(visit_types),
                        "day_offset": -(2 + i * 4),  # spread across the last ~3 weeks
                        "status": status,
                        "tier": label,
                    }
                )
            plan.upcoming.append(
                {
                    "patient_uuid": patient,
                    "provider_id": providers[cursor % len(providers)],
                    "visit_type_id": random.choice(visit_types),
                    "day_offset": random.randint(1, 21),
                    "tier": label,
                }
            )

    # Waitlist: some entries left waiting so the queue is visible, and some run
    # all the way through offer -> accept so "slots recovered" is a real number
    # produced by the backfill engine rather than a seeded constant.
    for i, patient in enumerate(patients[cursor : cursor + 14]):
        plan.waitlist.append(
            {
                "patient_uuid": patient,
                "provider_id": providers[i % len(providers)],
                "visit_type_id": random.choice(visit_types),
                "priority": random.choice([0, 1, 1, 2, 2, 3]),
                "backfill": i < 6,  # first six get offered and accepted
            }
        )
    return plan


def login(api_url: str, username: str, password: str) -> str:
    resp = httpx.post(
        f"{api_url.rstrip('/')}/auth/login",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Login failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url", default=os.environ.get("SCHEDULER_API_URL", "http://localhost:8000")
    )
    parser.add_argument("--username", default=os.environ.get("DEMO_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", ""))
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible runs")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
    if not args.password:
        parser.error("password required (--password or DEMO_PASSWORD)")

    print(f"Target: {args.api_url}")

    token = login(args.api_url, args.username, args.password)
    r = DemoRefresher(args.api_url, token, dry_run=args.dry_run)

    before = r.get("/dashboard/metrics")
    print(f"Before: {before}")

    providers = [p["id"] for p in r.get("/providers")]
    visit_types = [v["id"] for v in r.get("/visit-types")]
    existing = r.get("/appointments")
    if isinstance(existing, dict):
        existing = existing.get("items", [])
    patients = sorted({a["patient_uuid"] for a in existing})

    if not providers or not visit_types:
        raise SystemExit("No providers or visit types on this instance; seed it first.")
    if not patients:
        raise SystemExit(
            "No existing patients found. This script reuses patient UUIDs from existing "
            "appointments; it cannot create identity records over the API by design."
        )

    print(
        f"Found {len(providers)} providers, {len(visit_types)} visit types, "
        f"{len(patients)} distinct patients"
    )

    random.shuffle(patients)
    history = patient_history(existing)
    plan = build_plan(patients, providers, visit_types, history)
    print(f"Plan: {plan.summary()}")

    if args.dry_run:
        for tier, _, ratio, n in RISK_TIERS:
            print(f"  {tier:7} -> {n} past appts at {ratio:.0%} no-show, 1 upcoming")
        print("Dry run; nothing written.")
        return 0

    written = 0
    for item in plan.history:
        appt_id = r.book(
            item["provider_id"], item["patient_uuid"], item["visit_type_id"], item["day_offset"]
        )
        if appt_id and r.patch_status(appt_id, STATUS_ENDPOINT[item["status"]]):
            written += 1
    print(f"History written: {written}/{len(plan.history)}")

    booked = 0
    for item in plan.upcoming:
        if r.book(
            item["provider_id"], item["patient_uuid"], item["visit_type_id"], item["day_offset"]
        ):
            booked += 1
    print(f"Upcoming booked: {booked}/{len(plan.upcoming)}")

    added = recovered = 0
    for item in plan.waitlist:
        entry_id = r.add_waitlist(
            {
                "patient_uuid": item["patient_uuid"],
                "provider_id": item["provider_id"],
                "visit_type_id": item["visit_type_id"],
                "priority": item["priority"],
            }
        )
        if not entry_id:
            continue
        added += 1
        if item["backfill"] and r.backfill(entry_id):
            recovered += 1
    print(f"Waitlist added: {added}/{len(plan.waitlist)} (backfilled {recovered})")

    after = r.get("/dashboard/metrics")
    print(f"After:  {after}")

    if r.failures:
        print(f"\n{len(r.failures)} unexpected failures:", file=sys.stderr)
        for f in r.failures[:10]:
            print(f"  {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
