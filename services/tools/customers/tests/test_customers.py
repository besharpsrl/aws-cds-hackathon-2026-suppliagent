"""Tool `customers` (T-42): FN-03 acceptance criteria, F-02 cases and negative authorization."""

from types import SimpleNamespace
from typing import Any

import pytest
from suppliagent_shared.errors import AccessDeniedError, InvalidInputError, NotFoundError
from suppliagent_tool_customers import customers
from suppliagent_tool_customers.customers import (
    GetCustomerProfileInput,
    IdentifyContactInput,
    UpdatePrivacyInput,
    get_customer_profile,
    identify_contact,
    update_privacy,
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


def test_demo_customer_contact_is_verified_at_once(events: list[Any], aws: Any) -> None:
    result = identify(caller=UNKNOWN, customerCode="C90001", venueName="demo bistro")  # T-71
    assert result["status"] == "MATCHED"
    assert result["contact"]["status"] == "VERIFIED"
    assert result["customers"] == [{"customerId": "cus_901", "venueName": "Demo Bistro 1"}]
    contact_id = result["contact"]["contactId"]
    identity = aws.Table("suppliagent-test-channel-identities").get_item(
        Key={"channelAddress": NEW_PHONE}
    )["Item"]
    assert identity["verified"] is True
    assert events == [
        (
            "contact.identified",
            {"contactId": contact_id, "method": "CUSTOMER_CODE", "verified": True},
        )
    ]
    # full access from the next call: order history included, other venues still denied
    judge = caller("CUSTOMER_CONTACT", contact_id)
    assert profile(judge, "cus_901")["lastOrders"]
    with pytest.raises(AccessDeniedError):
        profile(judge, "cus_001")


def test_only_flagged_customers_verify_at_once(events: list[Any]) -> None:
    result = identify(caller=UNKNOWN, customerCode="C10006", venueName="Osteria del Ponte")
    assert result["contact"]["status"] == "PENDING_VERIFICATION"
    assert events[0][1]["verified"] is False


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


# --- privacy notice and proactive consent (FN-02, F-01) -------------------------------------

CON_003 = caller("CUSTOMER_CONTACT", "con_003", "WHATSAPP#+393330000003")  # no notice yet


@pytest.fixture
def notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVACY_NOTICE_VERSION", "v1")


def privacy(who: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return update_privacy(UpdatePrivacyInput.model_validate({"caller": who, **kwargs}))


def test_known_contact_sees_its_privacy_state() -> None:  # F-01
    assert identify(caller=CON_003)["privacy"] == {"noticeSent": False, "proactiveConsent": None}
    assert identify(caller=CON_001)["privacy"] == {"noticeSent": True, "proactiveConsent": True}
    assert identify(caller=caller("CUSTOMER_CONTACT", "con_002"))["privacy"] == {
        "noticeSent": True,
        "proactiveConsent": False,
    }


def test_sales_rep_gets_no_privacy_block() -> None:
    assert "privacy" not in identify(caller=REP_001)


def test_notice_is_recorded_once_with_date_and_version(
    notice: None, events: list[Any], aws: Any
) -> None:
    first = privacy(CON_003, noticeSent=True)
    assert first["status"] == "UPDATED"
    assert first["privacy"]["noticeSent"] is True
    stored = aws.Table("suppliagent-test-contacts").get_item(Key={"contactId": "con_003"})["Item"]
    assert stored["privacyNoticeVersion"] == "v1"
    sent_at = stored["privacyNoticeSentAt"]
    privacy(CON_003, noticeSent=True)  # a repeated call keeps the first record
    again = aws.Table("suppliagent-test-contacts").get_item(Key={"contactId": "con_003"})["Item"]
    assert again["privacyNoticeSentAt"] == sent_at
    assert "proactiveConsent" not in again  # C2: not asked, not given
    assert events[0] == (
        "contact.privacy_updated",
        {"contactId": "con_003", "channel": "WHATSAPP", "noticeSent": True},
    )


@pytest.mark.parametrize("answer", [True, False])  # F-01.C1, C2
def test_consent_is_recorded_with_date_channel_and_version(
    answer: bool, notice: None, events: list[Any], aws: Any
) -> None:
    result = privacy(CON_003, noticeSent=True, proactiveConsent=answer)
    assert result["privacy"]["proactiveConsent"] is answer
    stored = aws.Table("suppliagent-test-contacts").get_item(Key={"contactId": "con_003"})["Item"]
    assert stored["proactiveConsent"] is answer
    assert stored["proactiveConsentChannel"] == "WHATSAPP"
    assert stored["proactiveConsentVersion"] == "v1"
    assert stored["proactiveConsentAt"].endswith("Z")
    assert events[-1][1]["proactiveConsent"] is answer


def test_consent_can_be_revoked_at_any_time(notice: None) -> None:  # "Stop proposte"
    assert privacy(CON_001, proactiveConsent=False)["privacy"]["proactiveConsent"] is False
    assert identify(caller=CON_001)["privacy"]["proactiveConsent"] is False


def test_unknown_caller_notice_is_stored_on_the_new_contact(
    notice: None, events: list[Any], aws: Any
) -> None:  # F-01.C3: the notice came with the identification greeting
    result = identify(
        caller=UNKNOWN, customerCode="C10003", venueName="Bar Aurora", privacyNoticeSent=True
    )
    assert result["privacy"] == {"noticeSent": True, "proactiveConsent": None}
    contact = aws.Table("suppliagent-test-contacts").get_item(
        Key={"contactId": result["contact"]["contactId"]}
    )["Item"]
    assert contact["privacyNoticeVersion"] == "v1"
    assert contact["privacyNoticeSentAt"].endswith("Z")


def test_unknown_caller_without_notice_leaves_it_unsent() -> None:
    result = identify(caller=UNKNOWN, customerCode="C10003", venueName="Bar Aurora")
    assert result["privacy"]["noticeSent"] is False


@pytest.mark.parametrize(
    "who",
    [
        REP_001,  # staff, not a contact
        UNKNOWN,
        caller("CUSTOMER_CONTACT", None),
        caller("CUSTOMER_CONTACT", "con_nope"),  # not a contact: nothing is created
    ],
)
def test_update_privacy_is_denied_or_not_found_for_anyone_else(
    who: dict[str, Any], aws: Any
) -> None:
    before = len(aws.Table("suppliagent-test-contacts").scan()["Items"])
    with pytest.raises((AccessDeniedError, NotFoundError)):
        privacy(who, noticeSent=True)
    assert len(aws.Table("suppliagent-test-contacts").scan()["Items"]) == before


def test_update_privacy_only_touches_the_callers_own_contact(notice: None, aws: Any) -> None:
    privacy(CON_001, noticeSent=True, proactiveConsent=False)
    other = aws.Table("suppliagent-test-contacts").get_item(Key={"contactId": "con_002"})["Item"]
    assert other["proactiveConsent"] is False  # seed value, untouched
    assert "proactiveConsentAt" not in other


def test_update_privacy_needs_something_to_record() -> None:
    with pytest.raises(InvalidInputError):
        privacy(CON_003)


def test_model_cannot_name_another_contact_in_update_privacy() -> None:
    event = {"caller": CON_003, "contactId": "con_001", "proactiveConsent": False}
    assert lambda_handler(event, context("update_privacy")) == {"error": "INVALID_INPUT"}


def test_handler_routes_update_privacy(notice: None) -> None:
    result = lambda_handler(
        {"caller": CON_003, "proactiveConsent": True}, context("update_privacy")
    )
    assert result["status"] == "UPDATED"
    assert result["privacy"]["proactiveConsent"] is True


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


# --- set_order_email (FN-14, F-07.C7) -------------------------------------------------------

CON_003 = caller("CUSTOMER_CONTACT", "con_003", "WHATSAPP#+393330000003")  # no email on record


def set_email(who: dict[str, Any], email: str) -> dict[str, Any]:
    return customers.set_order_email(
        customers.SetOrderEmailInput.model_validate({"caller": who, "email": email})
    )


def test_order_email_is_stored_normalized_on_the_own_contact(events: list[Any], aws: Any) -> None:
    from suppliagent_shared.contacts import order_email

    assert order_email("con_003") is None
    result = set_email(CON_003, "  Paolo.Greco@Example.COM ")

    assert result == {"status": "UPDATED", "orderEmail": "paolo.greco@example.com"}
    item = aws.Table("suppliagent-test-contacts").get_item(Key={"contactId": "con_003"})["Item"]
    assert item["orderEmail"] == "paolo.greco@example.com" and "orderEmailAt" in item
    assert order_email("con_003") == "paolo.greco@example.com"
    assert events == [("contact.order_email_set", {"contactId": "con_003"})]
    # never a channel identity: mail from that address is not trusted as the contact
    identities = aws.Table("suppliagent-test-channel-identities").scan()["Items"]
    assert not any("paolo.greco" in i["channelAddress"] for i in identities)


def test_order_email_falls_back_to_the_verified_email_identity(aws: Any) -> None:
    from suppliagent_shared.contacts import order_email

    assert order_email("con_001") == "ordini.fornoantico@example.com"
    assert order_email("rep_001") == "marco.rinaldi@example.com"
    assert order_email(None) is None


def test_a_given_order_email_wins_and_clears_a_bounce(events: list[Any], aws: Any) -> None:
    from suppliagent_shared.contacts import order_email

    contacts = aws.Table("suppliagent-test-contacts")
    contacts.update_item(
        Key={"contactId": "con_001"},
        UpdateExpression="SET orderEmailBouncedAt = :ts",
        ExpressionAttributeValues={":ts": "2026-10-28T09:00:00Z"},
    )
    set_email(CON_001, "luca@example.org")

    assert order_email("con_001") == "luca@example.org"
    assert "orderEmailBouncedAt" not in contacts.get_item(Key={"contactId": "con_001"})["Item"]


@pytest.mark.parametrize(
    "email", ["", "not-an-email", "a@b", "Luca <luca@example.org>", "a@x.it, b@y.it", "a b@x.it"]
)
def test_invalid_order_email_is_refused(email: str, events: list[Any]) -> None:
    with pytest.raises(InvalidInputError):
        set_email(CON_003, email)
    assert events == []


@pytest.mark.parametrize("who", [REP_001, UNKNOWN, caller("CUSTOMER_CONTACT", None)])
def test_only_a_customer_contact_sets_its_own_order_email(
    who: dict[str, Any], events: list[Any]
) -> None:
    with pytest.raises(AccessDeniedError):
        set_email(who, "x@example.org")
    assert events == []


def test_order_email_of_an_unknown_contact_is_not_found(events: list[Any]) -> None:
    with pytest.raises(NotFoundError):
        set_email(caller("CUSTOMER_CONTACT", "con_999"), "x@example.org")
    assert events == []


def test_set_order_email_through_the_gateway_handler(events: list[Any]) -> None:
    context = SimpleNamespace(
        client_context=SimpleNamespace(
            custom={"bedrockAgentCoreToolName": "customers___set_order_email"}
        )
    )
    ok = lambda_handler({"caller": CON_003, "email": "p@example.org"}, context)
    assert ok == {"status": "UPDATED", "orderEmail": "p@example.org"}
    assert lambda_handler({"caller": REP_001, "email": "p@example.org"}, context) == {
        "error": "ACCESS_DENIED"
    }


@pytest.mark.parametrize(
    "args",
    [
        {"vatNumber": "IT-90000000901", "venueName": "Demo Bistro 1"},
        {"vatNumber": "P.IVA 90000000901", "venueName": "demo bistro 1"},
        {"vatNumber": "it 900 000 00901", "venueName": "Demo Bistro"},
        {"customerCode": "c 90001", "venueName": "Demo Bistro"},
        {"customerCode": "C-90001", "venueName": "Demo Bistro"},
    ],
)
def test_unknown_matched_with_loosely_written_code_or_vat(args: dict[str, str]) -> None:  # F-02
    assert identify(caller=UNKNOWN, **args)["status"] == "MATCHED"


@pytest.mark.parametrize(
    ("vat", "venue"),
    [
        ("90000000002", "Da Nino"),  # short name, without the venue type
        ("90000000003", "Aurora"),
        ("90000000001", "Forno Antico S.r.l."),  # legal name
        ("90000000006", "Osteria del Ponte S.a.s."),
    ],
)
def test_unknown_matched_with_short_or_legal_name(vat: str, venue: str) -> None:  # F-02
    assert identify(caller=UNKNOWN, vatNumber=vat, venueName=venue)["status"] == "MATCHED"


def test_unknown_other_venue_number_not_matched() -> None:  # F-02.C3
    result = identify(caller=UNKNOWN, customerCode="C90001", venueName="Trattoria Da Nino")
    assert result == {"status": "NOT_FOUND"}
