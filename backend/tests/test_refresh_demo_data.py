"""Unit tests for the demo-refresh planner.

Only the pure planning functions are covered here; the HTTP side is exercised by
running the script against a live instance. The planner is what is easy to get
subtly wrong, because the ratio scorer counts a patient's entire history rather
than a recent window -- so appointments already present on the target instance
shift the result.
"""

import importlib.util
import pathlib
import sys

import pytest

_spec = importlib.util.spec_from_file_location(
    "refresh_demo_data",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "refresh_demo_data.py",
)
refresh = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass resolves annotations via sys.modules.
sys.modules["refresh_demo_data"] = refresh
_spec.loader.exec_module(refresh)

LOW, HIGH = 0.2, 0.5  # settings.risk_low_threshold / risk_high_threshold


def _final_ratio(existing: tuple[int, int], added: tuple[int, int]) -> float:
    n_no_show, n_completed = added
    total = existing[0] + n_no_show + n_completed
    return (existing[1] + n_no_show) / total


class TestPatientHistory:
    def test_counts_only_resolved_appointments(self):
        appts = [
            {"patient_uuid": "a", "status": "completed"},
            {"patient_uuid": "a", "status": "no_show"},
            {"patient_uuid": "a", "status": "scheduled"},
            {"patient_uuid": "a", "status": "cancelled"},
        ]
        assert refresh.patient_history(appts) == {"a": (2, 1)}

    def test_patients_with_no_resolved_history_are_absent(self):
        appts = [{"patient_uuid": "b", "status": "scheduled"}]
        assert refresh.patient_history(appts) == {}

    def test_separates_patients(self):
        appts = [
            {"patient_uuid": "a", "status": "no_show"},
            {"patient_uuid": "b", "status": "completed"},
        ]
        assert refresh.patient_history(appts) == {"a": (1, 1), "b": (1, 0)}


class TestPlanAdditions:
    def test_splits_add_up_to_the_requested_total(self):
        for existing in [(0, 0), (2, 1), (9, 4)]:
            for ratio in [0.0, 0.05, 0.33, 0.65, 1.0]:
                n_no_show, n_completed = refresh.plan_additions(existing, ratio, 6)
                assert n_no_show + n_completed == 6
                assert n_no_show >= 0 and n_completed >= 0

    def test_no_existing_history_hits_the_target(self):
        n_no_show, n_completed = refresh.plan_additions((0, 0), 0.65, 6)
        assert _final_ratio((0, 0), (n_no_show, n_completed)) == pytest.approx(0.667, abs=0.02)

    def test_compensates_for_existing_clean_history(self):
        """A patient who already attended twice needs more no-shows to read as high risk."""
        clean = refresh.plan_additions((2, 0), 0.65, 6)
        fresh = refresh.plan_additions((0, 0), 0.65, 6)
        assert clean[0] > fresh[0]

    def test_compensates_for_existing_no_shows(self):
        """A patient who already missed appointments needs fewer added to read as low risk."""
        dirty = refresh.plan_additions((4, 3), 0.05, 5)
        assert dirty[0] == 0  # add nothing but completions to dilute the ratio

    @pytest.mark.parametrize("existing", [(0, 0), (1, 0), (2, 0), (2, 1), (5, 1)])
    def test_tiers_land_in_their_intended_bucket(self, existing):
        """For reachable histories, each tier must produce its own colour."""
        buckets = {}
        for label, _count, ratio, to_add in refresh.RISK_TIERS:
            added = refresh.plan_additions(existing, ratio, to_add)
            ratio_out = _final_ratio(existing, added)
            buckets[label] = (
                "high" if ratio_out >= HIGH else "medium" if ratio_out >= LOW else "low"
            )
        assert buckets["high"] == "high", f"{existing} -> {buckets}"
        assert buckets["low"] == "low", f"{existing} -> {buckets}"
        assert buckets["medium"] == "medium", f"{existing} -> {buckets}"

    def test_a_heavy_no_show_history_cannot_be_dragged_down_to_low(self):
        """Documents why tier assignment is ordered by history rather than random.

        The scorer counts a patient's whole record. Someone sitting at 4 no-shows
        in 8 visits is at 0.31 even after 5 straight completions -- still medium,
        not low. Assigning that patient to the low tier would render the wrong
        colour, so build_plan sorts by existing ratio instead of picking at random.
        """
        added = refresh.plan_additions((8, 4), 0.05, 5)
        assert _final_ratio((8, 4), added) >= LOW

    def test_never_exceeds_available_slots(self):
        """An impossible target clamps instead of returning a negative count."""
        n_no_show, n_completed = refresh.plan_additions((10, 0), 0.9, 3)
        assert n_no_show == 3 and n_completed == 0

    def test_target_already_met_adds_no_no_shows(self):
        n_no_show, _ = refresh.plan_additions((10, 9), 0.05, 4)
        assert n_no_show == 0


class TestBuildPlan:
    def test_produces_history_upcoming_and_waitlist(self):
        patients = [f"p{i}" for i in range(40)]
        plan = refresh.build_plan(patients, ["prov1", "prov2"], ["vt1"], {})
        assert plan.history and plan.upcoming and plan.waitlist
        assert len(plan.upcoming) == sum(t[1] for t in refresh.RISK_TIERS)
        assert any(w["backfill"] for w in plan.waitlist)

    def test_all_history_lands_inside_the_dashboard_window(self):
        """Every generated past appointment must fall within the 30-day window."""
        plan = refresh.build_plan([f"p{i}" for i in range(40)], ["prov1"], ["vt1"], {})
        offsets = [item["day_offset"] for item in plan.history]
        assert all(-30 < o < 0 for o in offsets), f"out of window: {sorted(set(offsets))}"

    def test_upcoming_are_in_the_future(self):
        plan = refresh.build_plan([f"p{i}" for i in range(40)], ["prov1"], ["vt1"], {})
        assert all(item["day_offset"] > 0 for item in plan.upcoming)

    def test_does_not_reuse_a_patient_across_tiers(self):
        plan = refresh.build_plan([f"p{i}" for i in range(40)], ["prov1"], ["vt1"], {})
        tier_by_patient = {}
        for item in plan.history:
            tier_by_patient.setdefault(item["patient_uuid"], item["tier"])
            assert tier_by_patient[item["patient_uuid"]] == item["tier"]

    def test_handles_fewer_patients_than_tiers_need(self):
        plan = refresh.build_plan(["only-one"], ["prov1"], ["vt1"], {})
        assert len(plan.upcoming) == 1

    def test_tiers_are_assigned_worst_history_first(self):
        """The patient with the worst record must not land in the low tier."""
        patients = [f"p{i}" for i in range(40)]
        history = {"p0": (8, 4), "p1": (6, 3), "p39": (5, 0)}
        plan = refresh.build_plan(patients, ["prov1"], ["vt1"], history)

        tier_of = {item["patient_uuid"]: item["tier"] for item in plan.upcoming}
        assert tier_of["p0"] == "high"
        assert tier_of["p1"] == "high"
        # A clean record sorts to the back, so it is either untiered or not high.
        assert tier_of.get("p39") != "high"
