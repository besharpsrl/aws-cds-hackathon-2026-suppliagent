"""Tool `customers` (T-42): FN-03 acceptance criteria, F-02 cases and negative authorization."""

from types import SimpleNamespace
from typing import Any

import pytest
from suppliagent_shared.errors import AccessDeniedError, InvalidInputError
from suppliagent_tool_customers import customers
from suppliagent_tool_customers.customers import (
    GetCustomerProfileInput,
    IdentifyContactInput,
    get_customer_profile,
    identify_contact,
)
from suppliagent_tool_customers.handler import lambda_handler

NEW_PHONE = "WHATSAPP#+393339999999"


def caller(
    role: str, contact_id: str | None = None, address: str = NEW_PHONE, conv: str = "conv_1"
) -> dict[str, Any]:
    return {
        "role": role,
        "contactId": contact_id,
        "channelAddress": address,
        "conversationId": conv,
    }


CON_001 = caller("CUSTOMER_CONTACT", "con_001", "WHATSAPP#+393330000001")  # cus_001 + cus_005
REP_001 = caller("SALES_REP", "rep_001", "WHATSAPP#+393330000101")  # cus_001, cus_002, cus_003
UNKNOWN = caller("UNKNOWN")


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(customers, "put_event", lambda _src, dt, detail: sent.append((dt, detail)))
    return sent


def identify(**kwargs: Any) -> dict[str, Any]:
    return identify_contact(IdentifyContactInput.model_validate(kwargs))


def profile(who: dict[str, Any], customer_id: str) -> dict[str, Any]:
    return get_customer_profile(
        GetCustomerProfileInput.model_validate({"caller": who, "customerId": customer_id})
    )


# --- identify_contact -----------------------------------------------------------------------


def test_known_contact_gets_all_its_venues() -> None:  # FN-03 known numbers, F-02.C5
    result = identify(caller=CON_001)
    assert result["status"] == "KNOWN"
    assert result["role"] == "CUSTOMER_CONTACT"
    assert [c["customerId"] for c in result["customers"]] == ["cus_001", "cus_005"]
    assert result["contact"] == {"contactId": "con_001", "status": "VERIFIED"}


def test_known_sales_rep_gets_portfolio() -> None:
    result = identify(caller=REP_001)
    assert result["role"] == "SALES_REP"
    assert {c["customerId"] for c in result["customers"]} == {"cus_001", "cus_002", "cus_003"}


def test_unknown_matched_by_code_and_approximate_venue(events: list[Any], aws: Any) -> None:
    result = identify(caller=UNKNOWN, customerCode=" c10001 ", venueName="forno antico")
    assert result["status"] == "MATCHED"
    assert result["role"] == "CUSTOMER_CONTACT"
    assert result["customers"] == [
        {"customerId": "cus_001", "venueName": "Pizzeria Il Forno Antico"}
    ]
    contact_id = result["contact"]["contactId"]
    assert result["contact"]["status"] == "PENDING_VERIFICATION"

    identity = aws.Table("suppliagent-test-channel-identities").get_item(
        Key={"channelAddress": NEW_PHONE}
    )["Item"]
    assert identity["contactId"] == contact_id
    assert identity["verified"] is False
    contact = aws.Table("suppliagent-test-contacts").get_item(Key={"contactId": contact_id})["Item"]
    assert contact["customerIds"] == ["cus_001"]
    assert contact["status"] == "PENDING_VERIFICATION"
    assert events == [
        (
            "contact.identified",
            {"contactId": contact_id, "method": "CUSTOMER_CODE", "verified": False},
        )
    ]


def test_unknown_matched_by_vat_number_without_prefix(events: list[Any]) -> None:
    result = identify(caller=UNKNOWN, vatNumber="9000 0000 002", venueName="Trattoria da Nino")
    assert result["customers"][0]["customerId"] == "cus_002"
    assert events[0][1]["method"] == "VAT_NUMBER"


@pytest.mark.parametrize(
    "args",
    [
        {"customerCode": "C10001", "venueName": "Osteria del Ponte"},  # right code, wrong venue
        {"customerCode": "C10001", "venueName": "Pizzeria"},  # too generic to count as a match
        {"customerCode": "C99999", "venueName": "Pizzeria Il Forno Antico"},
    ],
)
def test_unknown_not_matched_writes_nothing(
    args: dict[str, str], events: list[Any], aws: Any
) -> None:
    assert identify(caller=UNKNOWN, **args) == {"status": "NOT_FOUND"}  # F-02.C3
    assert "Item" not in aws.Table("suppliagent-test-channel-identities").get_item(
        Key={"channelAddress": NEW_PHONE}
    )
    assert events == []


@pytest.mark.parametrize("args", [{}, {"customerCode": "C10001"}, {"venueName": "Bar Aurora"}])
def test_unknown_needs_code_or_vat_and_venue(args: dict[str, str]) -> None:
    with pytest.raises(InvalidInputError):
        identify(caller=UNKNOWN, **args)


def test_retry_after_match_reuses_the_same_contact(events: list[Any], aws: Any) -> None:
    first = identify(caller=UNKNOWN, customerCode="C10003", venueName="Bar Aurora")
    again = identify(caller=UNKNOWN, customerCode="C10003", venueName="Bar Aurora")
    assert again["contact"] == first["contact"]
    contacts = aws.Table("suppliagent-test-contacts").scan()["Items"]
    assert sum(c["status"] == "PENDING_VERIFICATION" for c in contacts) == 1


def test_registered_address_is_never_rebound_to_another_customer(
    events: list[Any], aws: Any
) -> None:
    # con_001's verified number arrives as UNKNOWN (stale context) with valid data for cus_003
    stale = caller("UNKNOWN", address="WHATSAPP#+393330000001")
    result = identify(caller=stale, customerCode="C10003", venueName="Bar Aurora")
    assert result["status"] == "KNOWN"
    assert result["contact"] == {"contactId": "con_001", "status": "VERIFIED"}
    assert "cus_003" not in {c["customerId"] for c in result["customers"]}
    assert len(aws.Table("suppliagent-test-contacts").scan()["Items"]) == 5  # seed only
    assert events == []


def test_identification_attempts_are_limited_per_conversation(events: list[Any]) -> None:
    for _ in range(3):  # F-02.C4
        assert identify(caller=UNKNOWN, customerCode="C10003", venueName="Bar X")["status"] == (
            "NOT_FOUND"
        )
    right = identify(caller=UNKNOWN, customerCode="C10003", venueName="Bar Aurora")
    assert right == {"status": "IDENTIFICATION_FAILED"}
    assert events == []
    other = caller("UNKNOWN", conv="conv_2")
    assert identify(caller=other, customerCode="C10003", venueName="Bar Aurora")["status"] == (
        "MATCHED"
    )


def test_unknown_identification_needs_a_conversation() -> None:
    with pytest.raises(InvalidInputError):
        identify(caller=caller("UNKNOWN", conv=""), customerCode="C10003", venueName="Bar Aurora")


# --- get_customer_profile -------------------------------------------------------------------


def test_contact_sees_own_venues_with_last_orders_but_no_insights() -> None:
    for customer_id in ("cus_001", "cus_005"):
        result = profile(CON_001, customer_id)
        assert result["customerId"] == customer_id
        dates = [o["date"] for o in result["lastOrders"]]
        assert len(dates) == 5
        assert dates == sorted(dates, reverse=True)
        assert result.keys().isdisjoint({"insights", *customers.INTERNAL_FIELDS})


def test_sales_rep_sees_portfolio_customer_with_insights() -> None:
    result = profile(REP_001, "cus_002")
    assert result["insights"]["droppedProducts"] == ["PROSC-COTTO-KG"]
    assert result.keys() >= set(customers.INTERNAL_FIELDS)


def test_pending_contact_gets_venue_data_only(events: list[Any]) -> None:  # F-02.C2
    match = identify(caller=UNKNOWN, customerCode="C10003", venueName="Bar Aurora")
    pending = caller("CUSTOMER_CONTACT", match["contact"]["contactId"])
    result = profile(pending, "cus_003")
    assert result["venueName"] == "Bar Aurora"
    assert "lastOrders" not in result
    known = identify(caller=pending)
    assert known["contact"]["status"] == "PENDING_VERIFICATION"
    assert [c["customerId"] for c in known["customers"]] == ["cus_003"]


def test_contact_with_any_other_status_gets_nothing(aws: Any) -> None:
    contacts = aws.Table("suppliagent-test-contacts")
    contacts.update_item(
        Key={"contactId": "con_002"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "BLOCKED"},
    )
    blocked = caller("CUSTOMER_CONTACT", "con_002", "WHATSAPP#+393330000002")
    with pytest.raises(AccessDeniedError):
        profile(blocked, "cus_002")
    assert identify(caller=blocked) == {"status": "NOT_FOUND"}


@pytest.mark.parametrize(
    ("who", "customer_id"),
    [
        (CON_001, "cus_002"),  # another customer's venue
        (REP_001, "cus_004"),  # outside the rep's portfolio
        (REP_001, "cus_005"),  # con_001's second venue belongs to rep_002
        (UNKNOWN, "cus_001"),
        (caller("SALES_REP", "con_002"), "cus_002"),  # role/id mismatch grants nothing
        (caller("CUSTOMER_CONTACT", "con_nope"), "cus_001"),
        (CON_001, "cus_404"),
    ],
)
def test_profile_access_denied(who: dict[str, Any], customer_id: str) -> None:
    with pytest.raises(AccessDeniedError):
        profile(who, customer_id)


# --- handler --------------------------------------------------------------------------------


def context(tool: str) -> Any:
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"customers___{tool}"})
    )


def test_handler_routes_by_gateway_tool_name_and_returns_plain_json() -> None:
    result = lambda_handler(
        {"caller": CON_001, "customerId": "cus_001"}, context("get_customer_profile")
    )
    quantity = result["lastOrders"][0]["lines"][0]["quantity"]
    assert type(quantity) is int  # DynamoDB Decimal converted


@pytest.mark.parametrize(
    ("event", "tool", "error"),
    [
        ({"caller": CON_001, "customerId": "cus_002"}, "get_customer_profile", "ACCESS_DENIED"),
        # scope comes from DynamoDB: extra fields smuggled into the caller are rejected
        (
            {"caller": {**CON_001, "customerIds": ["cus_002"]}, "customerId": "cus_002"},
            "get_customer_profile",
            "INVALID_INPUT",
        ),
        ({"customerId": "cus_001"}, "get_customer_profile", "INVALID_INPUT"),
        ({"caller": CON_001}, "delete_everything", "UNKNOWN_TOOL"),
        (
            {
                "caller": caller("UNKNOWN", address="FAX#123"),
                "customerCode": "C10003",
                "venueName": "Bar Aurora",
            },
            "identify_contact",
            "INVALID_INPUT",
        ),
    ],
)
def test_handler_returns_error_codes(event: dict[str, Any], tool: str, error: str) -> None:
    assert lambda_handler(event, context(tool)) == {"error": error}


def test_handler_hides_unexpected_failures() -> None:
    assert lambda_handler({}, SimpleNamespace(client_context=None)) == {"error": "INTERNAL_ERROR"}
