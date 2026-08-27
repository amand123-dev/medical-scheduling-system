"""
Guards on the ML demo's synthetic demographic profiles.

These were a sidecar JSON file keyed by patient_uuid, written by
seed_synthetic.py. That failed twice over: the seed mints fresh UUIDs on every
run, so a re-seed orphaned every profile in the committed file, and on Fly the
file sits on an ephemeral disk, so any deploy restored the stale copy baked
into the image. Either way the UI silently showed "unavailable". Deriving the
profile from the UUID removes the stored state that could go stale.
"""

from __future__ import annotations

import uuid

import pytest

from app.scorer.ml import FEATURE_COLUMNS, demo_profile

KEYS = ("age", "gender", "scholarship", "hipertension", "diabetes", "alcoholism", "handcap")


class TestDeterminism:
    def test_same_uuid_always_gives_the_same_profile(self):
        u = "82271d78-1111-2222-3333-444455556666"
        assert demo_profile(u) == demo_profile(u)

    def test_accepts_a_uuid_object_and_a_string_alike(self):
        """The router passes str(patient_uuid); nothing should hinge on the type."""
        u = uuid.uuid4()
        assert demo_profile(u) == demo_profile(str(u))

    def test_different_uuids_give_different_profiles(self):
        """A constant profile for everyone would make the demo meaningless."""
        profiles = {tuple(demo_profile(str(uuid.uuid4()))[k] for k in KEYS) for _ in range(200)}
        assert len(profiles) > 100


class TestSurvivesAReseed:
    def test_any_freshly_minted_uuid_resolves(self):
        """
        The actual bug: a re-seed produced UUIDs absent from the profile file,
        and every one of them 404'd as "No demo profile for this patient."
        """
        for _ in range(50):
            assert demo_profile(str(uuid.uuid4())) is not None

    def test_needs_no_file_on_disk(self, tmp_path, monkeypatch):
        """Nothing may be read from the filesystem, which on Fly is ephemeral."""
        monkeypatch.chdir(tmp_path)
        assert demo_profile(str(uuid.uuid4()))["age"] >= 18


class TestShape:
    def test_supplies_every_demographic_feature_the_model_needs(self):
        """
        The model also needs SMS_received and wait_days, but those come from the
        operational DB, not the profile.
        """
        profile = demo_profile(str(uuid.uuid4()))
        from_db = {"SMS_received", "wait_days"}
        expected = {c.lower() for c in FEATURE_COLUMNS if c not in from_db}
        assert expected <= set(profile)

    @pytest.mark.parametrize("_", range(30))
    def test_values_stay_in_the_ranges_the_kaggle_model_was_trained_on(self, _):
        p = demo_profile(str(uuid.uuid4()))
        assert 18 <= p["age"] <= 85
        assert p["gender"] in (0, 1)
        assert 0 <= p["handcap"] <= 2
        for flag in ("scholarship", "hipertension", "diabetes", "alcoholism"):
            assert p[flag] in (0, 1)

    def test_is_labelled_as_synthetic(self):
        """CLAUDE.md: synthetic data only. The label travels with the data."""
        assert "Synthetic" in demo_profile(str(uuid.uuid4()))["_note"]
