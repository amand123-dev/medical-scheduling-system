"""
Guards on the timezone the synthetic scheduler data is anchored to.

WORK_HOURS in the seed are clinic *wall-clock* hours, and the scheduling engine
resolves work hours against a caller-supplied tz_offset. So the seed has to
anchor to the clinic's timezone rather than the seeding machine's. Running the
seed inside the Fly container (UTC) stored 8 AM as 08:00Z, which a browser in
New York draws at 4 AM -- four hours outside the work-hours band those same
rows claim to sit in. SEED_TIMEZONE exists to pin it.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_synthetic.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("seed_synthetic", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed():
    return _load_module()


class TestClinicNow:
    def test_defaults_to_machine_local_when_unset(self, seed, monkeypatch):
        monkeypatch.delenv("SEED_TIMEZONE", raising=False)
        assert seed.clinic_now().utcoffset() == datetime.now().astimezone().utcoffset()

    def test_blank_is_treated_as_unset(self, seed, monkeypatch):
        monkeypatch.setenv("SEED_TIMEZONE", "   ")
        assert seed.clinic_now().utcoffset() == datetime.now().astimezone().utcoffset()

    def test_named_timezone_wins_over_the_machine(self, seed, monkeypatch):
        """
        Deliberately probes a zone that is *not* the machine's, so the assert
        cannot pass by coincidence. Asserting against America/New_York would be
        vacuous on an Eastern laptop and only bite in CI.
        """
        local = datetime.now().astimezone().utcoffset()
        probe = next(
            z
            for z in ("Asia/Tokyo", "Pacific/Kiritimati")
            if datetime.now(ZoneInfo(z)).utcoffset() != local
        )
        monkeypatch.setenv("SEED_TIMEZONE", probe)
        assert seed.clinic_now().utcoffset() == datetime.now(ZoneInfo(probe)).utcoffset()
        assert seed.clinic_now().utcoffset() != local

    def test_returns_an_aware_datetime(self, seed, monkeypatch):
        monkeypatch.setenv("SEED_TIMEZONE", "America/New_York")
        assert seed.clinic_now().tzinfo is not None

    def test_unknown_timezone_falls_back_instead_of_crashing(self, seed, monkeypatch, capsys):
        """A typo in a deploy env var should not abort a re-seed half way."""
        monkeypatch.setenv("SEED_TIMEZONE", "America/Not_A_Place")
        now = seed.clinic_now()
        assert now.utcoffset() == datetime.now().astimezone().utcoffset()
        assert "not a known IANA timezone" in capsys.readouterr().out


class TestWorkHoursAreClinicLocal:
    def test_every_seeded_hour_lands_inside_the_work_day(self, seed, monkeypatch):
        """
        The bug this pins: with SEED_TIMEZONE set, every WORK_HOURS choice must
        still read back as that same wall-clock hour in the clinic's zone.
        """
        monkeypatch.setenv("SEED_TIMEZONE", "America/New_York")
        now = seed.clinic_now()
        for hour in seed.WORK_HOURS:
            start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            local = start.astimezone(ZoneInfo("America/New_York"))
            assert local.hour == hour
            assert 8 <= local.hour <= 16

    def test_utc_seeding_is_what_shifts_hours_out_of_band(self, seed, monkeypatch):
        """
        Demonstrates the failure directly: anchoring to UTC puts the 8 AM slot
        at 4 AM Eastern. This is why SEED_TIMEZONE is not cosmetic.
        """
        monkeypatch.setenv("SEED_TIMEZONE", "UTC")
        start = seed.clinic_now().replace(hour=8, minute=0, second=0, microsecond=0)
        eastern = start.astimezone(ZoneInfo("America/New_York")).hour
        assert eastern < 8
