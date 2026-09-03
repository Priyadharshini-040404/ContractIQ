"""
ContractIQ - Test Synthesizer Unit Tests

Covers core/test_synthesizer.py: ResourceDiscovery, AssertionSynthesizer,
and Synthesizer. Uses small synthetic endpoint dicts (in the same
shape OpenAPIParser.get_endpoint_summary() produces) rather than a real
spec file, so each behavior can be tested in isolation — including
constraint combinations no single real API happens to exercise.
"""

import pytest

import core.test_synthesizer as synth_module
from core.test_synthesizer import (
    AssertionSynthesizer,
    ResourceDiscovery,
    _collection_path_for,
    _declared_validation_status,
    _primary_success_status,
    _required_response_fields,
    _status_codes,
)

# Aliased (not imported as a bare name) so pytest's class-based
# collection heuristics don't try to treat the production
# TestSynthesizer class as a test class just because of its name.
Synthesizer = synth_module.TestSynthesizer


def ep(
    method,
    path,
    operation_id=None,
    parameters=None,
    request_body=None,
    responses=None,
):
    return {
        "method": method,
        "path": path,
        "operation_id": operation_id or f"{method.lower()}_{path}",
        "summary": "",
        "tags": [],
        "parameters": parameters or [],
        "request_body": request_body,
        "responses": responses or [],
    }


# ---------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------

class TestPathHelpers:
    def test_collection_path_strips_trailing_param(self):
        assert _collection_path_for("/api/v1/widgets/{widget_id}", "widget_id") == "/api/v1/widgets"

    def test_collection_path_root_level_param(self):
        assert _collection_path_for("/{thing_id}", "thing_id") == "/"

    def test_collection_path_returns_none_when_param_not_at_end(self):
        assert _collection_path_for("/api/v1/widgets/{widget_id}/extra", "widget_id") is None

    def test_collection_path_returns_none_for_unrelated_param(self):
        assert _collection_path_for("/api/v1/widgets/{widget_id}", "other_id") is None


class TestStatusHelpers:
    def test_status_codes_filters_by_prefix(self):
        endpoint = ep("GET", "/x", responses=[
            {"status_code": "200", "schema": {}},
            {"status_code": "404", "schema": {}},
            {"status_code": "422", "schema": {}},
        ])
        assert _status_codes(endpoint, "2") == [200]
        assert _status_codes(endpoint, "4") == [404, 422]

    def test_primary_success_status_defaults_to_200_when_none_declared(self):
        assert _primary_success_status(ep("GET", "/x", responses=[])) == 200

    def test_primary_success_status_picks_lowest_2xx(self):
        endpoint = ep("POST", "/x", responses=[
            {"status_code": "201", "schema": {}},
            {"status_code": "200", "schema": {}},
        ])
        assert _primary_success_status(endpoint) == 200

    def test_declared_validation_status_prefers_422_over_400(self):
        endpoint = ep("POST", "/x", responses=[
            {"status_code": "400", "schema": {}},
            {"status_code": "422", "schema": {}},
        ])
        assert _declared_validation_status(endpoint) == 422

    def test_declared_validation_status_falls_back_to_400(self):
        endpoint = ep("POST", "/x", responses=[{"status_code": "400", "schema": {}}])
        assert _declared_validation_status(endpoint) == 400

    def test_declared_validation_status_none_when_undeclared(self):
        endpoint = ep("POST", "/x", responses=[{"status_code": "404", "schema": {}}])
        assert _declared_validation_status(endpoint) is None

    def test_required_response_fields_falls_back_to_all_properties(self):
        endpoint = ep("GET", "/x", responses=[
            {"status_code": "200", "schema": {"properties": {"a": {}, "b": {}}}},
        ])
        assert _required_response_fields(endpoint, 200) == ["a", "b"]

    def test_required_response_fields_respects_cap(self):
        props = {f"f{i}": {} for i in range(10)}
        endpoint = ep("GET", "/x", responses=[{"status_code": "200", "schema": {"properties": props}}])
        assert len(_required_response_fields(endpoint, 200, cap=3)) == 3


# ---------------------------------------------------------------------
# ResourceDiscovery
# ---------------------------------------------------------------------

class TestResourceDiscovery:
    def test_discovers_creator_for_item_endpoint(self):
        endpoints = [
            ep("POST", "/api/v1/widgets", operation_id="create_widget",
               responses=[{"status_code": "201", "schema": {"properties": {"id": {"type": "string"}}}}]),
            ep("GET", "/api/v1/widgets/{widget_id}", operation_id="get_widget"),
        ]
        creators = ResourceDiscovery(endpoints).discover()
        assert "widget_id" in creators
        assert creators["widget_id"]["path"] == "/api/v1/widgets"
        assert creators["widget_id"]["capture"] == "id"

    def test_no_creator_when_no_matching_post_exists(self):
        endpoints = [ep("GET", "/api/v1/widgets/{widget_id}", operation_id="get_widget")]
        creators = ResourceDiscovery(endpoints).discover()
        assert creators == {}

    def test_infer_id_field_falls_back_to_param_name(self):
        endpoints = [
            ep("POST", "/api/v1/widgets", operation_id="create_widget",
               responses=[{"status_code": "201",
                           "schema": {"properties": {"widget_id": {"type": "string"}}}}]),
            ep("GET", "/api/v1/widgets/{widget_id}", operation_id="get_widget"),
        ]
        creators = ResourceDiscovery(endpoints).discover()
        assert creators["widget_id"]["capture"] == "widget_id"

    def test_infer_id_field_defaults_to_id_when_absent(self):
        endpoints = [
            ep("POST", "/api/v1/widgets", operation_id="create_widget",
               responses=[{"status_code": "201", "schema": {"properties": {"name": {"type": "string"}}}}]),
            ep("GET", "/api/v1/widgets/{widget_id}", operation_id="get_widget"),
        ]
        creators = ResourceDiscovery(endpoints).discover()
        assert creators["widget_id"]["capture"] == "id"


# ---------------------------------------------------------------------
# AssertionSynthesizer
# ---------------------------------------------------------------------

class TestAssertionSynthesizer:
    def test_json_response_gets_type_check_and_required_fields(self):
        endpoint = ep("GET", "/api/v1/widgets/{widget_id}", responses=[
            {"status_code": "200", "schema": {"required": ["id", "name"],
                                               "properties": {"id": {}, "name": {}}}},
        ])
        tc = {"expected": {"status_code": 200, "response_type": "json"}}
        assertions = AssertionSynthesizer().synthesize(tc, endpoint)
        types = [a["type"] for a in assertions]
        assert "status_code" in types
        fields = [a["field"] for a in assertions if a["field"]]
        assert "id" in fields and "name" in fields

    def test_empty_response_204_skips_body_assertions(self):
        tc = {"expected": {"status_code": 204, "response_type": "empty"}}
        assertions = AssertionSynthesizer().synthesize(tc, None)
        assert not any(a["field"] for a in assertions)
        body_assertion = next(a for a in assertions if a["type"] == "response_body")
        assert body_assertion["expected_value"] == "none"

    def test_response_body_contains_adds_exists_assertions_without_duplicating(self):
        endpoint = ep("POST", "/x", responses=[
            {"status_code": "422", "schema": {"required": ["detail"], "properties": {"detail": {}}}},
        ])
        tc = {"expected": {"status_code": 422, "response_type": "json",
                            "response_body_contains": ["detail"]}}
        assertions = AssertionSynthesizer().synthesize(tc, endpoint)
        detail_assertions = [a for a in assertions if a["field"] == "detail"]
        assert len(detail_assertions) == 1  # not duplicated

    def test_works_with_no_endpoint_info(self):
        tc = {"expected": {"status_code": 200, "response_type": "json"}}
        assertions = AssertionSynthesizer().synthesize(tc, None)
        assert any(a["type"] == "status_code" for a in assertions)


# ---------------------------------------------------------------------
# TestSynthesizer — fixtures modeling a small generic "Widget" API
# ---------------------------------------------------------------------

WIDGET_CREATE_SCHEMA = {
    "type": "object",
    "required": ["name", "quantity"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 20},
        "quantity": {"type": "integer", "minimum": 1, "maximum": 100},
        "category": {"type": "string", "enum": ["a", "b"]},
        "note": {"type": "string"},
    },
}


def widget_endpoints():
    return [
        ep("POST", "/api/v1/widgets", operation_id="create_widget",
           request_body={"required": True, "content_type": "application/json", "schema": WIDGET_CREATE_SCHEMA},
           responses=[
               {"status_code": "201", "schema": {"properties": {"id": {"type": "string"}, "name": {"type": "string"}}}},
               {"status_code": "422", "schema": {"properties": {"detail": {"type": "string"}}}},
           ]),
        ep("GET", "/api/v1/widgets/{widget_id}", operation_id="get_widget",
           parameters=[{"name": "widget_id", "location": "path", "required": True,
                        "schema": {"type": "string", "example": "sample-widget-001"}, "description": ""}],
           responses=[
               {"status_code": "200", "schema": {"required": ["id"], "properties": {"id": {"type": "string"}}}},
               {"status_code": "404", "schema": {"properties": {"detail": {"type": "string"}}}},
           ]),
        ep("DELETE", "/api/v1/widgets/{widget_id}", operation_id="delete_widget",
           parameters=[{"name": "widget_id", "location": "path", "required": True,
                        "schema": {"type": "string"}, "description": ""}],
           responses=[
               {"status_code": "204", "schema": {}},
               {"status_code": "404", "schema": {"properties": {"detail": {"type": "string"}}}},
           ]),
        ep("PUT", "/api/v1/widgets/{widget_id}", operation_id="update_widget",
           parameters=[{"name": "widget_id", "location": "path", "required": True,
                        "schema": {"type": "string"}, "description": ""}],
           request_body={"required": True, "content_type": "application/json",
                         "schema": {"type": "object", "properties": {"name": {"type": "string"}}}},
           responses=[
               {"status_code": "200", "schema": {"properties": {"id": {"type": "string"}}}},
               {"status_code": "404", "schema": {"properties": {"detail": {"type": "string"}}}},
           ]),
        ep("GET", "/api/v1/widgets", operation_id="list_widgets",
           responses=[{"status_code": "200", "schema": {"type": "array"}}]),
    ]


def spec_data_for(endpoints, create_resource=None):
    return {
        "endpoints": endpoints,
        "schemas": {},
        "server_url": "http://localhost:8000",
    }


class TestTestSynthesizerSampleGeneration:
    def test_sample_scalar_uses_example_when_present(self):
        assert Synthesizer._sample_scalar("x", {"example": "custom"}) == "custom"

    def test_sample_scalar_enum_uses_first_value(self):
        assert Synthesizer._sample_scalar("x", {"type": "string", "enum": ["a", "b"]}) == "a"

    def test_sample_scalar_string_respects_min_length(self):
        value = Synthesizer._sample_scalar("nm", {"type": "string", "minLength": 20})
        assert len(value) >= 20

    def test_sample_scalar_number_without_minimum_defaults(self):
        assert Synthesizer._sample_scalar("price", {"type": "number"}) == 100.0

    def test_sample_scalar_boolean_and_array_and_object(self):
        assert Synthesizer._sample_scalar("f", {"type": "boolean"}) is True
        assert Synthesizer._sample_scalar("f", {"type": "array"}) == ["test_item"]
        assert Synthesizer._sample_scalar("f", {"type": "object"}) == {}

    def test_sample_scalar_unknown_type_returns_none(self):
        assert Synthesizer._sample_scalar("f", {"type": "null"}) is None

    def test_invalid_value_enum(self):
        value, reason = Synthesizer._invalid_value_for({"enum": ["a", "b"]})
        assert value not in ("a", "b")
        assert "enum" in reason

    def test_invalid_value_enum_collision_handled(self):
        value, _ = Synthesizer._invalid_value_for(
            {"enum": ["__contractiq_invalid_enum_value__"]}
        )
        assert value != "__contractiq_invalid_enum_value__"

    def test_invalid_value_integer_maximum(self):
        value, reason = Synthesizer._invalid_value_for({"type": "integer", "maximum": 10})
        assert value == 11 and "maximum" in reason

    def test_invalid_value_integer_minimum(self):
        value, reason = Synthesizer._invalid_value_for({"type": "integer", "minimum": 5})
        assert value == 4 and "minimum" in reason

    def test_invalid_value_exclusive_maximum(self):
        value, reason = Synthesizer._invalid_value_for({"type": "number", "exclusiveMaximum": 9.5})
        assert value == 9.5 and "exclusiveMaximum" in reason

    def test_invalid_value_exclusive_minimum(self):
        value, reason = Synthesizer._invalid_value_for({"type": "number", "exclusiveMinimum": 0})
        assert value == 0 and "exclusiveMinimum" in reason

    def test_invalid_value_string_max_length(self):
        value, reason = Synthesizer._invalid_value_for({"type": "string", "maxLength": 5})
        assert len(value) == 6

    def test_invalid_value_string_min_length(self):
        value, reason = Synthesizer._invalid_value_for({"type": "string", "minLength": 3})
        assert value == ""

    def test_invalid_value_none_when_unconstrained(self):
        assert Synthesizer._invalid_value_for({"type": "string"}) is None
        assert Synthesizer._invalid_value_for({"type": "boolean"}) is None


class TestTestSynthesizerGeneration:
    @pytest.fixture
    def synth(self):
        return Synthesizer(spec_data_for(widget_endpoints()))

    def test_generate_tests_produces_a_suite_per_endpoint(self, synth):
        result = synth.generate_tests()
        assert len(result["test_suites"]) == len(widget_endpoints())

    def test_positive_test_present_for_every_endpoint(self, synth):
        result = synth.generate_tests()
        for suite in result["test_suites"]:
            assert any(tc["type"] == "positive" for tc in suite["test_cases"])

    def test_delete_test_has_setup_block_and_token_placeholder(self, synth):
        result = synth.generate_tests()
        delete_suite = next(s for s in result["test_suites"] if s["operation_id"] == "delete_widget")
        positive = next(tc for tc in delete_suite["test_cases"] if tc["type"] == "positive")
        assert positive["request"]["path"] == "/api/v1/widgets/{{token}}"
        assert positive["setup"]["path"] == "/api/v1/widgets"
        assert positive["setup"]["capture"] == "id"
        assert "name" in positive["setup"]["body"]

    def test_no_unsubstituted_single_brace_params_anywhere(self, synth):
        result = synth.generate_tests()
        for suite in result["test_suites"]:
            for tc in suite["test_cases"]:
                assert "{widget_id}" not in tc["request"]["path"]

    def test_negative_test_generated_when_404_declared(self, synth):
        result = synth.generate_tests()
        get_suite = next(s for s in result["test_suites"] if s["operation_id"] == "get_widget")
        assert any(tc["type"] == "negative" for tc in get_suite["test_cases"])

    def test_negative_test_skipped_when_no_path_param(self, synth):
        result = synth.generate_tests()
        list_suite = next(s for s in result["test_suites"] if s["operation_id"] == "list_widgets")
        assert not any(tc["type"] == "negative" for tc in list_suite["test_cases"])

    def test_empty_body_test_expects_validation_status_when_required_fields_exist(self, synth):
        result = synth.generate_tests()
        create_suite = next(s for s in result["test_suites"] if s["operation_id"] == "create_widget")
        edge = next(tc for tc in create_suite["test_cases"] if tc["type"] == "edge_case" and "edge_01" in tc["test_id"])
        assert edge["expected"]["status_code"] == 422

    def test_empty_body_test_expects_success_when_no_required_fields(self, synth):
        result = synth.generate_tests()
        update_suite = next(s for s in result["test_suites"] if s["operation_id"] == "update_widget")
        edge = next(tc for tc in update_suite["test_cases"] if tc["type"] == "edge_case")
        assert edge["expected"]["status_code"] == 200

    def test_boundary_tests_scale_with_constraint_count(self, synth):
        result = synth.generate_tests()
        create_suite = next(s for s in result["test_suites"] if s["operation_id"] == "create_widget")
        boundary_tests = [tc for tc in create_suite["test_cases"] if "boundary" in tc["test_id"]]
        # name (minLength/maxLength), quantity (min/max), category (enum) -> 3 constrained props
        # note is unconstrained -> no boundary test for it.
        assert len(boundary_tests) == 3

    def test_boundary_tests_skipped_when_no_validation_status_declared(self):
        endpoints = [
            ep("POST", "/api/v1/things", operation_id="create_thing",
               request_body={"required": True, "content_type": "application/json",
                             "schema": {"type": "object", "properties": {
                                 "n": {"type": "integer", "maximum": 5}}}},
               responses=[{"status_code": "201", "schema": {"properties": {"id": {}}}}]),
        ]
        synth = Synthesizer(spec_data_for(endpoints))
        result = synth.generate_tests()
        assert not any("boundary" in tc["test_id"] for tc in result["test_suites"][0]["test_cases"])

    def test_response_type_empty_for_204(self, synth):
        result = synth.generate_tests()
        delete_suite = next(s for s in result["test_suites"] if s["operation_id"] == "delete_widget")
        positive = next(tc for tc in delete_suite["test_cases"] if tc["type"] == "positive")
        assert positive["expected"]["response_type"] == "empty"

    def test_generate_assertions_covers_every_test_case(self, synth):
        tests = synth.generate_tests()
        total_tests = sum(len(s["test_cases"]) for s in tests["test_suites"])
        assertions = synth.generate_assertions(tests)
        assert len(assertions["assertions"]) == total_tests


class TestTestSynthesizerLiveResourceCreation:
    def test_uses_create_resource_callback_for_shared_ids(self):
        calls = []

        def fake_create(path, body):
            calls.append((path, body))
            return {"id": "live-widget-42"}

        synth = Synthesizer(spec_data_for(widget_endpoints()), create_resource=fake_create)
        assert calls  # the creator endpoint was invoked during __init__
        result = synth.generate_tests()
        get_suite = next(s for s in result["test_suites"] if s["operation_id"] == "get_widget")
        positive = next(tc for tc in get_suite["test_cases"] if tc["type"] == "positive")
        assert "live-widget-42" in positive["request"]["path"]

    def test_falls_back_to_placeholder_when_create_resource_returns_none(self):
        synth = Synthesizer(spec_data_for(widget_endpoints()), create_resource=lambda p, b: None)
        result = synth.generate_tests()
        get_suite = next(s for s in result["test_suites"] if s["operation_id"] == "get_widget")
        positive = next(tc for tc in get_suite["test_cases"] if tc["type"] == "positive")
        # falls back to the path parameter's own declared example
        assert "sample-widget-001" in positive["request"]["path"]

    def test_placeholder_uses_integer_default_when_schema_says_integer(self):
        endpoints = [
            ep("POST", "/api/v1/counters", operation_id="create_counter",
               responses=[{"status_code": "201", "schema": {"properties": {"id": {}}}}]),
            ep("GET", "/api/v1/counters/{counter_id}", operation_id="get_counter",
               parameters=[{"name": "counter_id", "location": "path", "required": True,
                            "schema": {"type": "integer"}, "description": ""}],
               responses=[{"status_code": "200", "schema": {"properties": {"id": {}}}}]),
        ]
        synth = Synthesizer(spec_data_for(endpoints), create_resource=lambda p, b: None)
        result = synth.generate_tests()
        suite = next(s for s in result["test_suites"] if s["operation_id"] == "get_counter")
        positive = next(tc for tc in suite["test_cases"] if tc["type"] == "positive")
        assert positive["request"]["path"] == "/api/v1/counters/1"

    def test_body_field_reuses_shared_id_by_naming_convention(self):
        """A request-body property that shares its name with an already
        -resolved path parameter (e.g. 'widget_id') should reuse that
        real ID rather than a synthetic value, so cross-references
        stay valid."""
        endpoints = widget_endpoints() + [
            ep("POST", "/api/v1/orders", operation_id="create_order",
               request_body={"required": True, "content_type": "application/json",
                             "schema": {"type": "object", "required": ["widget_id"],
                                        "properties": {"widget_id": {"type": "string"}}}},
               responses=[{"status_code": "201", "schema": {"properties": {"id": {}}}}]),
        ]
        synth = Synthesizer(spec_data_for(endpoints), create_resource=lambda p, b: {"id": "live-42"})
        result = synth.generate_tests()
        order_suite = next(s for s in result["test_suites"] if s["operation_id"] == "create_order")
        positive = next(tc for tc in order_suite["test_cases"] if tc["type"] == "positive")
        assert positive["request"]["body"]["widget_id"] == "live-42"
