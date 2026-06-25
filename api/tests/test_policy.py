from armoriq_api.models import Policy
from armoriq_api.policy import PolicyEngine
from armoriq_api.types import ToolExecutionIntent


def make_intent(tool_name: str = "write_file", path: str = "sandbox/demo.txt") -> ToolExecutionIntent:
    return ToolExecutionIntent(
        conversation_id="conversation-1",
        run_id="run-1",
        server_id="server-1",
        server_name="local-sandbox",
        tool_name=tool_name,
        arguments={"path": path},
        token_budget=100,
        cost_budget=1.0,
        spent_tokens=10,
        spent_cost=0.1,
    )


def make_policy(**overrides) -> Policy:
    payload = {
        "id": "policy-1",
        "name": "default",
        "rule_type": "block_tool",
        "enabled": True,
        "priority": 100,
        "target_tool": "delete_file",
        "target_server_id": None,
        "conditions_json": None,
        "action_json": {"reason": "No deletes"},
    }
    payload.update(overrides)
    return Policy(**payload)


def test_block_rule_wins() -> None:
    engine = PolicyEngine()
    decision = engine.evaluate(make_intent(tool_name="delete_file"), [make_policy()])
    assert decision.verdict == "block"
    assert "No deletes" in decision.reason


def test_require_approval_rule() -> None:
    engine = PolicyEngine()
    policy = make_policy(
        rule_type="require_approval",
        action_json={"reason": "Needs review"},
        target_tool="write_file",
    )
    decision = engine.evaluate(make_intent(tool_name="write_file"), [policy])
    assert decision.verdict == "require_approval"
    assert decision.requires_approval is True


def test_validate_args_blocks_bad_path() -> None:
    engine = PolicyEngine()
    policy = make_policy(
        rule_type="validate_args",
        target_tool="write_file",
        conditions_json={"path_arg": "path", "allow_prefixes": ["sandbox/"]},
        action_json=None,
    )
    decision = engine.evaluate(make_intent(path="../escape.txt"), [policy])
    assert decision.verdict == "block"
    assert "must not escape" in decision.reason


def test_validate_args_blocks_normalized_escape_outside_prefix() -> None:
    engine = PolicyEngine()
    policy = make_policy(
        rule_type="validate_args",
        target_tool="write_file",
        conditions_json={"path_arg": "path", "allow_prefixes": ["notes/"]},
        action_json=None,
    )

    decision = engine.evaluate(make_intent(path="notes/../secret.txt"), [policy])

    assert decision.verdict == "block"
    assert "must stay under one of" in decision.reason


def test_validate_args_allows_normalized_path_inside_prefix() -> None:
    engine = PolicyEngine()
    policy = make_policy(
        rule_type="validate_args",
        target_tool="write_file",
        conditions_json={"path_arg": "path", "allow_prefixes": ["notes/"]},
        action_json=None,
    )

    decision = engine.evaluate(make_intent(path="notes/sub/../demo.txt"), [policy])

    assert decision.verdict == "allow"


def test_tool_scope_matches_human_readable_tool_name() -> None:
    engine = PolicyEngine()
    policy = make_policy(target_tool="list files", action_json={"reason": "Privacy"})

    decision = engine.evaluate(make_intent(tool_name="list_files"), [policy])

    assert decision.verdict == "block"
    assert decision.reason == "Privacy"
