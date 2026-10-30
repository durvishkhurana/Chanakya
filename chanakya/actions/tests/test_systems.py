import pytest

from chanakya.actions.registry import InvalidArgumentsError, MockToolRegistry
from chanakya.actions.systems.db import FailurePolicy, MockDB
from chanakya.actions.systems.seed import FORMER_MERCHANTS, MERCHANTS, seed
from chanakya.actions.systems.tools import TOOLS, complete_onboarding, default_slot
from chanakya.core.interfaces import ToolRegistry, UnknownToolError
from chanakya.core.schemas import ToolCall, ToolKind


def registry(**failures) -> MockToolRegistry:
    db = MockDB(failures={system: FailurePolicy(rate=rate) for system, rate in failures.items()})
    seed(db)
    return MockToolRegistry(db)


def call(tool, **args) -> ToolCall:
    return ToolCall(mission_id="m_test", tool=tool, args=args)


HAPPY = {
    "create_callback_request": {"merchant_id": "mer_ramesh", "product": "soundbox", "note": "evening"},
    "get_merchant_profile": {"merchant_id": "mer_ramesh"},
    "create_lead": {"merchant_id": "mer_ramesh", "product": "soundbox"},
    "update_lead_stage": {"merchant_id": "mer_ramesh", "product": "soundbox", "stage": "interested"},
    "log_interaction": {"merchant_id": "mer_ramesh", "summary": "Asked about charges"},
    "send_onboarding_link": {"merchant_id": "mer_ramesh", "product": "soundbox", "language": "hi-IN"},
    "send_onboarding_reminder": {"merchant_id": "mer_imran", "session_id": "onb_imran_stalled"},
    "send_summary": {"merchant_id": "mer_ramesh", "text": "Dhanyavaad"},
    "get_onboarding_status": {"merchant_id": "mer_imran"},
    "book_field_visit": {"merchant_id": "mer_gurpreet", "purpose": "technician", "slot": default_slot()},
    "book_callback": {"merchant_id": "mer_sharma", "due_at": default_slot(2), "note": "after lunch"},
    "get_device_status": {"merchant_id": "mer_gurpreet"},
    "get_device_usage": {"merchant_id": "mer_gurpreet"},
    "get_device_order_status": {"merchant_id": "mer_ramesh"},
    "raise_ticket": {"merchant_id": "mer_lakshmi", "category": "settlement", "description": "Delayed settlement"},
    "get_settlement_status": {"merchant_id": "mer_lakshmi"},
}


def test_registry_satisfies_the_core_protocol():
    assert isinstance(registry(), ToolRegistry)


def test_every_tool_has_a_happy_path_case():
    assert set(HAPPY) | {"get_ticket_status"} == {tool.name for tool in TOOLS}


@pytest.mark.parametrize("name", sorted(HAPPY))
def test_happy_path(name):
    result = registry().execute(call(name, **HAPPY[name]))
    assert result.ok, result.error


@pytest.mark.parametrize("name", sorted(HAPPY))
def test_failure_path_returns_an_error_result(name):
    reg = registry()
    system = reg.get(name).system
    reg.db.failures[system] = FailurePolicy(rate=1.0)
    result = reg.execute(call(name, **HAPPY[name]))
    assert not result.ok and "unavailable" in result.error


def test_ticket_round_trip():
    reg = registry()
    ticket = reg.execute(call("raise_ticket", **HAPPY["raise_ticket"])).data["ticket_id"]
    owner = HAPPY["raise_ticket"]["merchant_id"]
    assert reg.execute(call("get_ticket_status", merchant_id=owner, ticket_id=ticket)).data["ticket"]["status"] == "open"
    assert not reg.execute(call("get_ticket_status", merchant_id=owner, ticket_id="tkt_missing")).ok
    # Another merchant's ticket is never readable, even by its exact id.
    assert not reg.execute(call("get_ticket_status", merchant_id="mer_ramesh" if owner != "mer_ramesh" else "mer_imran",
                                ticket_id=ticket)).ok


def test_visit_and_callback_times_must_be_iso_date_times():
    reg = registry()
    for tool, field in (("book_field_visit", "slot"), ("book_callback", "due_at")):
        bad = HAPPY[tool] | {field: "tomorrow evening"}
        try:
            reg.validate(call(tool, **bad))
        except InvalidArgumentsError:
            continue
        raise AssertionError(f"{tool} accepted a free-text {field}")


def test_unknown_tools_and_bad_arguments_are_rejected():
    reg = registry()
    with pytest.raises(UnknownToolError):
        reg.validate(call("give_free_rental", merchant_id="mer_ramesh"))
    with pytest.raises(InvalidArgumentsError):
        reg.validate(call("create_lead", merchant_id="mer_ramesh", product="loan"))
    with pytest.raises(InvalidArgumentsError):
        reg.validate(call("create_lead", merchant_id="mer_ramesh", product="soundbox", otp="1234"))


def test_unknown_merchant_is_a_failed_result_not_a_crash():
    result = registry().execute(call("get_device_status", merchant_id="mer_nobody"))
    assert not result.ok and "unknown merchant" in result.error


def test_onboarding_link_creates_session_and_outbox_message_then_completes():
    reg = registry()
    sent = reg.execute(call("send_onboarding_link", merchant_id="mer_ramesh", product="soundbox")).data
    assert sent["link"] == f"/demo/onboard/{sent['session_id']}"
    assert "Ramesh Kirana Store" in sent["body"]
    outbox = reg.db.all("SELECT * FROM outbox WHERE merchant_id = 'mer_ramesh'")
    assert outbox[0]["mission_id"] == "m_test" and outbox[0]["link"] == sent["link"]

    status = reg.execute(call("get_onboarding_status", merchant_id="mer_ramesh", session_id=sent["session_id"]))
    assert status.data["status"] == "pending"
    complete_onboarding(reg.db, sent["session_id"])
    status = reg.execute(call("get_onboarding_status", merchant_id="mer_ramesh"))
    assert status.data["status"] == "completed"
    assert reg.execute(call("get_merchant_profile", merchant_id="mer_ramesh")).data["merchant"]["has_soundbox"] == 1


def test_device_usage_reports_idle_days():
    devices = registry().execute(call("get_device_usage", merchant_id="mer_gurpreet")).data["devices"]
    assert devices[0]["days_since_last_payment"] >= 7


def test_tools_describe_kind_and_schema():
    reg = registry()
    link = reg.get("send_onboarding_link")
    assert link.kind == ToolKind.WRITE and link.irreversible and "product" in link.args_schema["properties"]
    assert reg.get("get_device_status").kind == ToolKind.READ
    assert all(info.description.startswith("Mock ") for info in reg.tools())
    assert reg.get("missing") is None


def test_seed_is_idempotent():
    db = MockDB()
    seed(db)
    seed(db)
    assert len(db.all("SELECT id FROM merchants")) == len(MERCHANTS) + len(FORMER_MERCHANTS)


def test_failures_are_reproducible_with_a_seed():
    def outcomes(seed_value):
        db = MockDB(seed=seed_value, failures={"crm": FailurePolicy(rate=0.5)})
        seed(db)
        reg = MockToolRegistry(db)
        return [reg.execute(call("get_merchant_profile", merchant_id="mer_ramesh")).ok for _ in range(20)]

    assert outcomes(7) == outcomes(7)
    assert True in outcomes(7) and False in outcomes(7)


def test_the_reminder_is_fixed_text_for_an_open_session_only():
    reg = registry()
    sent = reg.execute(call("send_onboarding_reminder", merchant_id="mer_imran", session_id="onb_imran_stalled"))
    assert sent.ok and "yaad dila rahe hain" in sent.data["body"] and sent.data["link"].endswith("onb_imran_stalled")
    with pytest.raises(InvalidArgumentsError):
        reg.validate(call("send_onboarding_reminder", merchant_id="mer_imran", session_id="onb_imran_stalled",
                          text="Free rental for you"))
    assert not reg.execute(call("send_onboarding_reminder", merchant_id="mer_ramesh", session_id="onb_imran_stalled")).ok
    complete_onboarding(reg.db, "onb_imran_stalled")
    done = reg.execute(call("send_onboarding_reminder", merchant_id="mer_imran", session_id="onb_imran_stalled"))
    assert not done.ok and "already completed" in done.error


def test_an_older_database_gains_the_win_back_columns_on_open(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE merchants (id TEXT PRIMARY KEY, name TEXT NOT NULL, business_type TEXT NOT NULL, "
                "city TEXT NOT NULL, language TEXT NOT NULL, start_hour INTEGER NOT NULL, end_hour INTEGER NOT NULL, "
                "do_not_call INTEGER NOT NULL DEFAULT 0, has_soundbox INTEGER NOT NULL DEFAULT 0, "
                "has_card_machine INTEGER NOT NULL DEFAULT 0, phone_last4 TEXT)")
    old.execute("INSERT INTO merchants VALUES ('mer_old', 'Old', 'kirana', 'Patna', 'hi-IN', 9, 18, 0, 1, 0, NULL)")
    old.commit()
    old.close()
    db = MockDB(path)
    seed(db)
    row = db.one("SELECT relationship, churned_at FROM merchants WHERE id = 'mer_old'")
    assert row == {"relationship": "customer", "churned_at": None}
    assert len(db.all("SELECT id FROM merchants")) == len(MERCHANTS) + len(FORMER_MERCHANTS) + 1


def test_former_merchants_are_seeded_with_a_reason_to_have_left():
    db = MockDB()
    seed(db)
    former = db.all("SELECT id, churned_at FROM merchants WHERE relationship = 'former' ORDER BY id")
    assert [m["id"] for m in former] == sorted(m[0] for m in FORMER_MERCHANTS) and all(m["churned_at"] for m in former)
    assert db.all("SELECT relationship FROM merchants WHERE id = 'mer_ramesh'") == [{"relationship": "customer"}]
    returned = {d["merchant_id"] for d in db.all("SELECT merchant_id FROM devices WHERE status = 'returned'")}
    assert returned == {"mer_harish", "mer_joginder", "mer_kavita"}
    assert db.one("SELECT status FROM settlements WHERE merchant_id = 'mer_joginder'")["status"] == "delayed"
    assert db.one("SELECT status FROM tickets WHERE merchant_id = 'mer_kavita'")["status"] == "open"
