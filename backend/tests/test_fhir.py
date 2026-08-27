"""
Tests for the FHIR R4 client.

Run offline against a mock transport. The default FHIR base URL is a shared
public test server whose contents change without notice and which anyone can
write to, so a suite that asserts against live data is a suite that fails for
reasons unrelated to this code. Live checks are opt-in:

    pytest -m live
"""

from __future__ import annotations

import httpx
import pytest

from mcp_server import fhir


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _bundle(*resources: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": r} for r in resources],
    }


class TestProjections:
    def test_patient_projection_flattens_name(self):
        out = fhir.project_patient(
            {
                "id": "p1",
                "name": [{"given": ["Ada"], "family": "Lovelace"}],
                "gender": "female",
                "birthDate": "1815-12-10",
            }
        )
        assert out["name"] == "Ada Lovelace"
        assert out["fhir_id"] == "p1"
        assert out["deceased"] is False

    def test_patient_name_prefers_text(self):
        out = fhir.project_patient({"id": "p", "name": [{"text": "Full Name", "given": ["X"]}]})
        assert out["name"] == "Full Name"

    def test_patient_with_no_name_does_not_crash(self):
        """Real records on the public server routinely have no name at all."""
        assert fhir.project_patient({"id": "p"})["name"] is None

    def test_deceased_detected_from_either_field(self):
        assert fhir.project_patient({"id": "p", "deceasedBoolean": True})["deceased"] is True
        assert fhir.project_patient({"id": "p", "deceasedDateTime": "2020-01-01"})["deceased"]

    def test_condition_projection(self):
        out = fhir.project_condition(
            {
                "id": "c1",
                "code": {"text": "Essential hypertension"},
                "clinicalStatus": {"coding": [{"code": "active"}]},
            }
        )
        assert out["condition"] == "Essential hypertension"
        assert out["clinical_status"] == "active"

    def test_codeable_falls_back_through_text_display_code(self):
        assert fhir._codeable({"text": "T"}) == "T"
        assert fhir._codeable({"coding": [{"display": "D"}]}) == "D"
        assert fhir._codeable({"coding": [{"code": "C"}]}) == "C"
        assert fhir._codeable(None) is None
        assert fhir._codeable({}) is None

    def test_medication_projection_handles_reference_form(self):
        """medication[x] is a choice type — either inline concept or a reference."""
        inline = fhir.project_medication_request(
            {"id": "m", "medicationCodeableConcept": {"text": "Metformin"}, "status": "active"}
        )
        assert inline["medication"] == "Metformin"
        ref = fhir.project_medication_request(
            {"id": "m", "medicationReference": {"display": "Lisinopril"}}
        )
        assert ref["medication"] == "Lisinopril"

    def test_medication_dosage_uses_first_text(self):
        out = fhir.project_medication_request(
            {"id": "m", "dosageInstruction": [{}, {"text": "1 tab daily"}]}
        )
        assert out["dosage"] == "1 tab daily"

    def test_observation_quantity_joins_value_and_unit(self):
        out = fhir.project_observation(
            {
                "id": "o",
                "code": {"text": "Heart rate"},
                "valueQuantity": {"value": 118, "unit": "/min"},
            }
        )
        assert out["value"] == "118 /min"

    def test_observation_handles_non_quantity_values(self):
        assert (
            fhir.project_observation({"id": "o", "valueCodeableConcept": {"text": "Positive"}})[
                "value"
            ]
            == "Positive"
        )
        assert fhir.project_observation({"id": "o", "valueString": "note"})["value"] == "note"

    def test_observation_with_no_value(self):
        assert fhir.project_observation({"id": "o"})["value"] is None


class TestScoping:
    def test_supported_resources_are_allowed(self):
        for rt in fhir.SUPPORTED_RESOURCES:
            fhir.check_scope(rt)

    def test_out_of_scope_resource_is_refused(self):
        with pytest.raises(fhir.ScopeError):
            fhir.check_scope("DiagnosticReport")

    async def test_scope_is_checked_before_any_network_call(self):
        """Scope must be a property of the client, not a convention the tools follow."""
        called = False

        def handler(request):
            nonlocal called
            called = True
            return httpx.Response(200, json={})

        with pytest.raises(fhir.ScopeError):
            await fhir.get_resources_for_patient("Encounter", "p1", client=_client(handler))
        assert called is False, "a network request was made for an out-of-scope resource"


class TestErrorHandling:
    async def test_operation_outcome_message_is_surfaced(self):
        """An HTTP status alone loses the reason; FHIR puts it in an OperationOutcome."""
        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [
                {"severity": "error", "code": "processing", "diagnostics": "Resource not known"}
            ],
        }
        client = _client(lambda r: httpx.Response(404, json=outcome))
        with pytest.raises(fhir.FhirError, match="Resource not known"):
            await fhir.get_patient("nope", client=client)

    async def test_operation_outcome_on_a_200_is_still_an_error(self):
        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid", "diagnostics": "bad param"}],
        }
        client = _client(lambda r: httpx.Response(200, json=outcome))
        with pytest.raises(fhir.FhirError, match="bad param"):
            await fhir.get_patient("x", client=client)

    async def test_non_json_body_is_reported_with_status(self):
        client = _client(lambda r: httpx.Response(502, text="<html>gateway</html>"))
        with pytest.raises(fhir.FhirError, match="502"):
            await fhir.get_patient("x", client=client)

    async def test_timeout_names_the_server(self):
        def handler(request):
            raise httpx.TimeoutException("timed out")

        with pytest.raises(fhir.FhirError, match="timed out"):
            await fhir.get_patient("x", client=_client(handler))

    async def test_connection_failure_is_wrapped(self):
        def handler(request):
            raise httpx.ConnectError("refused")

        with pytest.raises(fhir.FhirError, match="Could not reach"):
            await fhir.get_patient("x", client=_client(handler))


class TestRequests:
    async def test_patient_search_is_scoped_and_capped(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json=_bundle({"id": "p1"}))

        await fhir.search_patients(family="Smith", count=10_000, client=_client(handler))
        assert "family=Smith" in seen["url"]
        assert f"_count={fhir.FHIR_MAX_COUNT}" in seen["url"], "count must be capped"

    async def test_patient_filter_is_server_side(self):
        """patient= must be sent to the server, not applied after fetching a bundle."""
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json=_bundle())

        await fhir.get_resources_for_patient("Condition", "abc", client=_client(handler))
        assert "patient=abc" in seen["url"]

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_a_missing_patient_id_is_refused_before_the_network_call(self, missing):
        """
        httpx drops None params, so an absent id would turn a patient-scoped
        search into an unscoped one returning arbitrary patients' clinical
        records. Caught live against the public server: passing None for the id
        returned three other people's Conditions with a 200.
        """
        called = []

        def handler(request):
            called.append(str(request.url))
            return httpx.Response(200, json=_bundle())

        with pytest.raises(fhir.FhirError) as exc:
            await fhir.get_resources_for_patient("Condition", missing, client=_client(handler))
        assert called == []
        assert "patient id is required" in str(exc.value)

    async def test_only_get_is_ever_issued(self):
        """The default base URL is a shared public server; there must be no write path."""
        methods = []

        def handler(request):
            methods.append(request.method)
            return httpx.Response(200, json=_bundle({"id": "x"}))

        c = _client(handler)
        await fhir.search_patients(client=c)
        await fhir.get_resources_for_patient("Observation", "p", client=c)
        assert set(methods) == {"GET"}

    async def test_extra_search_params_are_passed_through(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json=_bundle())

        await fhir.get_resources_for_patient(
            "Observation", "p", client=_client(handler), extra={"category": "vital-signs"}
        )
        assert "category=vital-signs" in seen["url"]

    async def test_bundle_without_entries_returns_empty(self):
        client = _client(lambda r: httpx.Response(200, json={"resourceType": "Bundle"}))
        out = await fhir.get_resources_for_patient("Condition", "p", client=client)
        assert out["count"] == 0 and out["records"] == []

    async def test_malformed_entries_are_skipped(self):
        bundle = {"resourceType": "Bundle", "entry": [{"search": {}}, {"resource": {"id": "c1"}}]}
        client = _client(lambda r: httpx.Response(200, json=bundle))
        out = await fhir.get_resources_for_patient("Condition", "p", client=client)
        assert out["count"] == 1


@pytest.mark.live
class TestLiveServer:
    """Opt-in: pytest -m live. Hits the real public FHIR server."""

    async def test_server_is_fhir_r4(self):
        info = await fhir.capability_summary()
        assert info["fhir_version"].startswith("4.")
