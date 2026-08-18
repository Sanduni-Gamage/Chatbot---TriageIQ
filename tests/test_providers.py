"""Provider-abstraction tests.

The Gemini translation layer is exercised without the SDK or an API key by constructing
the client directly and calling its pure functions.
"""

from __future__ import annotations

import json

import pytest

from triageiq.config import PROVIDERS, Config, load_config
from triageiq.llm import GeminiClient, MockClient, Usage, _gemini_schema, build_client, estimate_cost
from triageiq.tools import TOOL_SCHEMAS


# ---------------------------------------------------------------- config
def test_mock_is_used_when_no_key_present(monkeypatch):
    monkeypatch.delenv("TRIAGEIQ_MODE", raising=False)   # conftest pins this; test auto-detection
    cfg = load_config()
    assert cfg.is_mock
    assert isinstance(build_client(cfg), MockClient)


def test_provider_selected_from_available_key(monkeypatch):
    monkeypatch.delenv("TRIAGEIQ_MODE", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    cfg = load_config()
    assert cfg.provider == "gemini"
    assert cfg.model == PROVIDERS["gemini"][1]   # the provider's declared default
    assert cfg.mode == "live"


def test_explicit_provider_overrides_environment(monkeypatch):
    monkeypatch.setenv("TRIAGEIQ_PROVIDER", "gemini")
    monkeypatch.delenv("TRIAGEIQ_MODEL", raising=False)
    assert load_config(provider="anthropic").provider == "anthropic"


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown provider"):
        load_config(provider="not-a-provider")


def test_mock_mode_needs_no_sdk_for_any_provider(monkeypatch):
    """Mock short-circuits before any backend is constructed."""
    monkeypatch.setenv("TRIAGEIQ_MODE", "mock")
    cfg = load_config(provider="gemini")
    assert isinstance(build_client(cfg), MockClient)


# ---------------------------------------------------------------- pricing
def test_cost_estimated_per_model():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate_cost("gemini-3.6-flash", usage) == pytest.approx(2.80)
    assert estimate_cost("claude-sonnet-5", usage) == pytest.approx(18.0)


def test_default_gemini_model_is_priced():
    """A default model missing from PRICES would silently report $0.00 cost."""
    _, default_model = PROVIDERS["gemini"]
    assert estimate_cost(default_model, Usage(1_000_000, 0)) > 0


def test_unlisted_model_falls_back_to_its_family_rate():
    """New model ids appear constantly; a $0.00 cost column would be misleading."""
    assert estimate_cost("gemini-9.9-flash-lite", Usage(1_000_000, 0)) == pytest.approx(0.10)
    assert estimate_cost("claude-opus-99", Usage(1_000_000, 0)) == pytest.approx(15.0)


def test_wholly_unknown_model_costs_zero_rather_than_guessing():
    assert estimate_cost("mystery-model-x", Usage(1000, 1000)) == 0.0


@pytest.mark.parametrize("model", [
    "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.6-flash", "claude-sonnet-5",
])
def test_selectable_models_all_report_a_cost(model):
    assert estimate_cost(model, Usage(1_000_000, 0)) > 0


# ---------------------------------------------------------------- schema conversion
def test_union_types_collapsed_for_gemini():
    """Gemini rejects {"type": ["string", "null"]}; it must become a plain type."""
    submit = next(t for t in TOOL_SCHEMAS if t["name"] == "submit_triage")
    converted = _gemini_schema(submit["input_schema"])
    clause = converted["properties"]["coverage"]["properties"]["clause_id"]
    assert clause["type"] == "string"


def test_every_tool_schema_converts_without_union_types():
    def assert_no_unions(node):
        if isinstance(node, dict):
            assert not isinstance(node.get("type"), list), f"union type left in {node}"
            for value in node.values():
                assert_no_unions(value)
        elif isinstance(node, list):
            for item in node:
                assert_no_unions(item)

    for tool in TOOL_SCHEMAS:
        assert_no_unions(_gemini_schema(tool["input_schema"]))


def test_object_schemas_always_declare_properties():
    converted = _gemini_schema({"type": "object"})
    assert converted["properties"] == {}


# ---------------------------------------------------------------- message translation
@pytest.fixture
def gemini():
    """A GeminiClient with only the state the translation layer needs — no SDK, no API key."""
    client = object.__new__(GeminiClient)
    client._signatures = {}
    client._call_seq = 0
    return client


TRANSCRIPT = [
    {"role": "user", "content": "Triage this claim. CLAIM_JSON: {}"},
    {"role": "assistant", "content": [
        {"type": "text", "text": "Checking the policy."},
        {"type": "tool_use", "id": "tu_1", "name": "lookup_policy",
         "input": {"policy_id": "MOT-100234"}},
    ]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_1",
         "content": json.dumps({"status": "active"})},
    ]},
]


def test_assistant_role_becomes_model(gemini):
    assert [c["role"] for c in gemini._to_contents(TRANSCRIPT)] == ["user", "model", "user"]


def test_tool_use_becomes_function_call(gemini):
    call = gemini._to_contents(TRANSCRIPT)[1]["parts"][1]["function_call"]
    assert call["name"] == "lookup_policy"
    assert call["args"] == {"policy_id": "MOT-100234"}


def test_tool_result_resolves_id_to_tool_name(gemini):
    """Gemini matches results by tool NAME, not by the call id Anthropic uses."""
    response = gemini._to_contents(TRANSCRIPT)[2]["parts"][0]["function_response"]
    assert response["name"] == "lookup_policy"
    assert response["response"] == {"status": "active"}


def test_json_string_results_are_parsed_to_objects(gemini):
    """A function response must be a JSON object, not a string."""
    contents = gemini._to_contents(TRANSCRIPT)
    assert isinstance(contents[2]["parts"][0]["function_response"]["response"], dict)


def test_non_json_results_are_wrapped(gemini):
    transcript = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t", "name": "x", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "plain text"}]},
    ]
    response = gemini._to_contents(transcript)[1]["parts"][0]["function_response"]
    assert response["response"] == {"result": "plain text"}


def test_empty_text_blocks_are_dropped(gemini):
    transcript = [{"role": "assistant", "content": [{"type": "text", "text": ""}]}]
    assert gemini._to_contents(transcript) == []


# ---------------------------------------------------------------- response translation
class _FakePart:
    def __init__(self, text=None, function_call=None, thought_signature=None):
        self.text = text
        self.function_call = function_call
        self.thought_signature = thought_signature


class _FakeCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args
        self.id = None


class _FakeResponse:
    def __init__(self, parts, prompt=10, output=5):
        self.candidates = [type("C", (), {"content": type("X", (), {"parts": parts})()})()]
        self.usage_metadata = type("U", (), {"prompt_token_count": prompt,
                                             "candidates_token_count": output})()


def test_function_call_response_is_normalised(gemini):
    resp = gemini._from_response(
        _FakeResponse([_FakePart(function_call=_FakeCall("check_coverage", {"policy_id": "P1"}))])
    )
    assert resp.wants_tools
    assert resp.tool_uses[0].name == "check_coverage"
    assert resp.tool_uses[0].input == {"policy_id": "P1"}
    assert resp.tool_uses[0].id, "a call id must always be present for the transcript"


def test_text_only_response_ends_the_turn(gemini):
    resp = gemini._from_response(_FakeResponse([_FakePart(text="All done.")]))
    assert resp.text == "All done."
    assert not resp.wants_tools
    assert resp.stop_reason == "end_turn"


def test_usage_is_captured_for_cost_reporting(gemini):
    resp = gemini._from_response(_FakeResponse([_FakePart(text="hi")], prompt=123, output=45))
    assert resp.usage.input_tokens == 123
    assert resp.usage.output_tokens == 45


def test_empty_response_does_not_crash(gemini):
    resp = gemini._from_response(_FakeResponse([]))
    assert resp.text == ""
    assert resp.tool_uses == []


# ---------------------------------------------------------------- thought signatures
# Gemini 3.x rejects a replayed function call whose "thought signature" is missing
# (400 INVALID_ARGUMENT), so the round trip must preserve it.
def test_thought_signature_is_echoed_back_on_replay(gemini):
    client = gemini
    resp = client._from_response(_FakeResponse([
        _FakePart(function_call=_FakeCall("lookup_policy", {"policy_id": "P1"}),
                  thought_signature=b"sig-abc"),
    ]))
    call_id = resp.tool_uses[0].id

    contents = client._to_contents([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "lookup_policy", "input": {}}]},
    ])
    assert contents[0]["parts"][0]["thought_signature"] == b"sig-abc"


def test_missing_signature_is_simply_omitted(gemini):
    client = gemini
    resp = client._from_response(_FakeResponse([
        _FakePart(function_call=_FakeCall("lookup_policy", {}), thought_signature=None),
    ]))
    contents = client._to_contents([
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": resp.tool_uses[0].id, "name": "lookup_policy",
             "input": {}}]},
    ])
    assert "thought_signature" not in contents[0]["parts"][0]


def test_call_ids_stay_unique_across_claims(gemini):
    """One client is reused for all 100 eval claims; a repeated id would replay the wrong
    signature onto a different call."""
    client = gemini
    ids = []
    for _ in range(3):
        resp = client._from_response(_FakeResponse([
            _FakePart(function_call=_FakeCall("lookup_policy", {}), thought_signature=b"s"),
        ]))
        ids.append(resp.tool_uses[0].id)
    assert len(set(ids)) == 3
