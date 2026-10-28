"""FN-12 / FN-16 / FN-17 / FN-18 acceptance for the `orders` tool, incl. negative authorization."""

# ruff: noqa: N815 - wire names

from datetime import timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest
import suppliagent_tool_orders.orders as orders
from pydantic import BaseModel
from suppliagent_shared.auth import CallerContext
from suppliagent_shared.errors import (
    AccessDeniedError,
    ConfirmationMismatchError,
    ConflictError,
    InvalidInputError,
    InvalidSkuError,
    OrderLockedError,
)
from suppliagent_tool_orders.orders import (
    CancelOrderInput,
    ConfirmOrderInput,
    CreateOrderDraftInput,
    GetOrderStatusInput,
    ReportDeliveryIssueInput,
    RequestConfirmationInput,
    UpdateOrderDraftInput,
    cancel_order,
    confirm_order,
    create_order_draft,
    get_order_status,
    report_delivery_issue,
    request_order_confirmation,
    update_order_draft,
)

Events = list[tuple[str, dict[str, Any]]]


def make[T: BaseModel](cls: type[T], **kwargs: Any) -> T:
    """Validated model from plain values (the Gateway sends JSON, not typed objects)."""
    return cls.model_validate(kwargs)


def caller(role: str, contact: str | None, conversation: str = "conv_1") -> CallerContext:
    return make(
        CallerContext,
        role=role,
        contactId=contact,
        channelAddress="WHATSAPP#+393330000001",
        conversationId=conversation,
    )


CUSTOMER = caller("CUSTOMER_CONTACT", "con_001")  # owns cus_001 and cus_005
REP = caller("SALES_REP", "rep_001")  # portfolio cus_001..003
OTHER_REP = caller("SALES_REP", "rep_002")
STRANGER = caller("UNKNOWN", None)
OTHER_CUSTOMER = caller("CUSTOMER_CONTACT", "con_002", "conv_2")  # owns cus_002
THURSDAY = "2026-10-29"  # first delivery day of cus_001 (MON, THU) after Wed 28/10 10:00


def draft(
    who: CallerContext = CUSTOMER, customer: str = "cus_001", **overrides: Any
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "customerId": customer,
        "lines": [
            {"rawText": "mozz", "sku": "FDL-PIZZA-1KG", "quantity": 25},
            {"rawText": "farina", "sku": "FARINA-00-25KG", "quantity": 4},
        ],
        "deliveryDate": THURSDAY,
        **overrides,
    }
    out: dict[str, Any] = create_order_draft(make(CreateOrderDraftInput, caller=who, **args))[
        "order"
    ]
    return out


def pending(who: CallerContext = CUSTOMER) -> str:
    order = draft(who)
    out = request_order_confirmation(
        make(RequestConfirmationInput, caller=who, orderId=order["orderId"])
    )
    assert out["status"] == "PENDING_CONFIRMATION", out
    return str(order["orderId"])


def reply(aws: Any, conversation: str = "conv_1", direction: str = "INBOUND") -> None:
    """A message of the conversation stored after the summary (NOW is when it was shown)."""
    aws.Table("suppliagent-test-messages").put_item(
        Item={
            "conversationId": conversation,
            "tsMessageId": "2026-10-28T09:00:05.000Z#m_" + direction + conversation,
            "direction": direction,
        }
    )


def confirm(order_id: str, who: CallerContext = CUSTOMER, **extra: Any) -> dict[str, Any]:
    """The customer answered the summary, then the agent confirms (the normal case)."""
    reply(boto3.resource("dynamodb"), who.conversationId or "conv_1")
    return confirm_order(make(ConfirmOrderInput, caller=who, orderId=order_id, **extra))


def stored(aws: Any, order_id: str) -> dict[str, Any]:
    item: dict[str, Any] = aws.Table("suppliagent-test-orders").get_item(Key={"orderId": order_id})[
        "Item"
    ]
    return item


def kinds(events: Events) -> list[str]:
    return [kind for kind, _ in events]


# --- drafts --------------------------------------------------------------------------------


def test_draft_prices_and_names_come_from_the_catalog(events: Events) -> None:
    order = draft()
    assert order["status"] == "DRAFT" and order["total"] == Decimal(
        "256.00"
    )  # 25 x 6.80 + 4 x 21.50
    first = order["lines"][0]
    assert (first["name"], first["unit"], first["unitPrice"]) == (
        "Fior di latte per pizza 1 kg",
        "pz",
        Decimal("6.80"),
    )
    assert ("order.draft_created", {"orderId": order["orderId"], "source": "text"}) in events


def test_the_model_cannot_set_prices_or_names() -> None:
    with pytest.raises(ValueError):
        make(
            CreateOrderDraftInput,
            caller=CUSTOMER,
            customerId="cus_001",
            lines=[{"sku": "FDL-PIZZA-1KG", "quantity": 1, "unitPrice": 0.01}],
        )


def test_valid_promo_applies_to_the_line() -> None:
    order = draft(lines=[{"sku": "FDL-PIZZA-2KG", "quantity": 10}])
    assert order["lines"][0]["unitPrice"] == Decimal("12.40")


def test_unresolved_lines_make_the_order_need_clarification() -> None:
    order = draft(
        lines=[
            {"rawText": "mozz", "sku": "FDL-PIZZA-1KG", "quantity": 5},
            {"rawText": "burro", "quantity": 2, "candidates": ["BURRO-PAN-1KG"]},
        ]
    )
    assert order["status"] == "NEEDS_CLARIFICATION"
    assert order["lines"][1]["status"] == "AMBIGUOUS"
    assert order["lines"][1]["candidates"][0]["name"].startswith("Burro")


def test_a_second_create_in_the_same_conversation_returns_the_open_draft() -> None:
    first = draft()
    again = create_order_draft(
        make(
            CreateOrderDraftInput,
            caller=CUSTOMER,
            customerId="cus_001",
            lines=[{"sku": "OLIO-EVO-5L", "quantity": 1}],
        )
    )
    assert again["existing"] is True and again["order"]["orderId"] == first["orderId"]


def test_unknown_or_retired_sku_is_refused() -> None:
    for sku in ("NOPE", "BURRO-PAN-500"):
        with pytest.raises(InvalidSkuError):
            draft(lines=[{"sku": sku, "quantity": 1}])


def test_resolved_line_needs_sku_and_quantity() -> None:
    with pytest.raises(InvalidInputError):
        draft(lines=[{"sku": "FDL-PIZZA-1KG", "status": "SUBSTITUTED"}])


def test_draft_for_another_customer_is_denied() -> None:
    with pytest.raises(AccessDeniedError):
        draft(CUSTOMER, "cus_002")  # con_001 does not own cus_002
    with pytest.raises(AccessDeniedError):
        draft(OTHER_REP, "cus_001")  # not in rep_002's portfolio
    with pytest.raises(AccessDeniedError):
        draft(STRANGER)


def test_rep_orders_for_a_customer_of_the_portfolio(aws: Any) -> None:
    order = draft(REP, "cus_002")
    item = stored(aws, order["orderId"])
    assert item["createdBy"] == "rep_001" and item["source"] == "rep" and item["repId"] == "rep_001"


# --- update --------------------------------------------------------------------------------


def update(order_id: str, who: CallerContext = CUSTOMER, **args: Any) -> dict[str, Any]:
    return update_order_draft(make(UpdateOrderDraftInput, caller=who, orderId=order_id, **args))


def test_update_adds_changes_and_removes_lines_and_recomputes_the_total(events: Events) -> None:
    order = draft()
    out = update(
        order["orderId"],
        ops=[
            {"op": "update", "lineId": "l1", "quantity": 10},
            {"op": "remove", "lineId": "l2"},
            {"op": "add", "sku": "OLIO-EVO-5L", "quantity": 2},
        ],
    )["order"]
    assert [(ln["lineId"], ln["sku"]) for ln in out["lines"]] == [
        ("l1", "FDL-PIZZA-1KG"),
        ("l3", "OLIO-EVO-5L"),
    ]
    assert out["total"] == Decimal("144.00")  # 10 x 6.80 + 2 x 38.00


def test_resolving_the_last_unclear_line_moves_to_draft() -> None:
    order = draft(lines=[{"rawText": "burro", "quantity": 8, "candidates": ["BURRO-PAN-1KG"]}])
    assert order["status"] == "NEEDS_CLARIFICATION"
    out = update(order["orderId"], ops=[{"op": "update", "lineId": "l1", "sku": "BURRO-PAN-1KG"}])
    assert out["status"] == "DRAFT" and out["order"]["lines"][0]["status"] == "MATCHED"


def test_changing_a_sku_is_tracked_as_a_correction(events: Events) -> None:
    order = draft()
    update(
        order["orderId"],
        ops=[{"op": "update", "lineId": "l1", "sku": "FDL-PIZZA-2KG", "status": "SUBSTITUTED"}],
    )
    assert (
        "order.line_corrected",
        {
            "orderId": order["orderId"],
            "lineId": "l1",
            "by": "CUSTOMER_CONTACT",
            "fromSku": "FDL-PIZZA-1KG",
            "toSku": "FDL-PIZZA-2KG",
        },
    ) in events


def test_editing_the_summary_goes_back_to_draft() -> None:
    order_id = pending()
    out = update(order_id, ops=[{"op": "update", "lineId": "l2", "quantity": 5}])
    assert out["status"] == "DRAFT"  # F-07.C3 "Modifica"


def test_update_of_unknown_line_or_foreign_order() -> None:
    order = draft()
    with pytest.raises(InvalidInputError):
        update(order["orderId"], ops=[{"op": "remove", "lineId": "l9"}])
    with pytest.raises(AccessDeniedError):
        update(order["orderId"], OTHER_CUSTOMER, ops=[{"op": "remove", "lineId": "l1"}])
    with pytest.raises(AccessDeniedError):
        update("ord_doesnotexist", ops=[])


def test_concurrent_edit_is_a_conflict(monkeypatch: pytest.MonkeyPatch, aws: Any) -> None:
    order = draft()
    stale = stored(aws, order["orderId"])
    update(order["orderId"], ops=[{"op": "update", "lineId": "l1", "quantity": 3}])  # bumps version
    monkeypatch.setattr(orders, "_load", lambda _id: stale)
    with pytest.raises(ConflictError):
        update(order["orderId"], ops=[{"op": "update", "lineId": "l1", "quantity": 9}])
    assert stored(aws, order["orderId"])["lines"][0]["quantity"] == 3  # nothing was overwritten


# --- summary (F-07.2) ----------------------------------------------------------------------


def issues_of(order_id: str, who: CallerContext = CUSTOMER) -> dict[str, dict[str, Any]]:
    out = request_order_confirmation(make(RequestConfirmationInput, caller=who, orderId=order_id))
    assert out["status"] == "NEEDS_FIXES", out
    return {i["code"]: i for i in out["issues"]}


def test_summary_moves_to_pending_confirmation_with_everything_to_show(events: Events) -> None:
    order = draft(deliveryNotes="citofono rotto")
    out = request_order_confirmation(
        make(RequestConfirmationInput, caller=CUSTOMER, orderId=order["orderId"])
    )
    summary = out["summary"]
    assert out["status"] == summary["status"] == "PENDING_CONFIRMATION"
    assert summary["deliveryDate"] == THURSDAY and summary["deliveryNotes"] == "citofono rotto"
    assert summary["total"] == Decimal("256.00") and len(summary["lines"]) == 2
    assert (
        "order.status_changed",
        {
            "orderId": order["orderId"],
            "from": "DRAFT",
            "to": "PENDING_CONFIRMATION",
            "ts": events[-1][1]["ts"],
        },
    ) in events


def test_summary_is_refused_while_something_is_unclear() -> None:
    order = draft(lines=[{"rawText": "burro", "candidates": ["BURRO-PAN-1KG"]}], deliveryDate=None)
    codes = issues_of(order["orderId"])
    assert codes["UNRESOLVED_LINES"]["lineIds"] == ["l1"]
    assert codes["NO_LINES"] and codes["NO_DELIVERY_DATE"]["options"][0] == THURSDAY


def test_pack_multiple_is_proposed_not_applied() -> None:
    order = draft(
        lines=[{"sku": "BURRO-PAN-1KG", "quantity": 3}, {"sku": "FARINA-00-25KG", "quantity": 5}]
    )
    issue = issues_of(order["orderId"])["NOT_A_MULTIPLE"]
    assert (issue["lineId"], issue["multiple"], issue["roundedQuantity"]) == ("l1", 8, 8)


def test_below_minimum_says_how_much_is_missing() -> None:
    order = draft(lines=[{"sku": "FDL-PIZZA-1KG", "quantity": 5}])  # 34.00
    issue = issues_of(order["orderId"])["BELOW_MINIMUM"]
    assert issue["missing"] == Decimal("46.00")


def test_delivery_date_must_be_a_served_day_before_the_cutoff() -> None:
    friday = draft(deliveryDate="2026-10-30")  # cus_001 is served on MON, THU
    issue = issues_of(friday["orderId"])["INVALID_DELIVERY_DATE"]
    assert issue["options"][:2] == [THURSDAY, "2026-11-02"]


def test_after_the_cutoff_the_next_day_is_no_longer_possible(clock: Any) -> None:
    clock.now = clock.now.replace(hour=18, minute=30)  # Wed 19:30 in Rome: Thursday is gone
    order = draft()
    assert issues_of(order["orderId"])["INVALID_DELIVERY_DATE"]["options"][0] == "2026-11-02"


def test_summary_of_a_closed_state_order() -> None:
    order_id = pending()
    confirm(order_id)
    out = request_order_confirmation(
        make(RequestConfirmationInput, caller=CUSTOMER, orderId=order_id)
    )
    assert out == {"status": "NOT_CONFIRMABLE", "orderStatus": "CONFIRMED"}


# --- confirmation (FN-12) --------------------------------------------------------------------


def test_confirm_moves_to_confirmed_and_emits_order_confirmed_once(
    events: Events, aws: Any
) -> None:
    order_id = pending()
    out = confirm(order_id)
    assert out["status"] == "CONFIRMED" and out["order"]["status"] == "CONFIRMED"
    item = stored(aws, order_id)
    assert item["status"] == "CONFIRMED" and item["confirmedBy"] == "con_001"
    assert all(ln["status"] == "CONFIRMED" for ln in item["lines"])
    assert [d for k, d in events if k == "order.confirmed"] == [
        {"orderId": order_id, "value": 256.0, "lines": 2, "createdBy": "con_001"}
    ]


def test_double_tap_makes_one_order(events: Events) -> None:
    order_id = pending()
    first, second = confirm(order_id), confirm(order_id, idempotencyKey="other-key")
    assert (first["status"], second["status"]) == ("CONFIRMED", "ALREADY_CONFIRMED")
    assert kinds(events).count("order.confirmed") == 1
    assert kinds(events).count("order.status_changed") == 2  # DRAFT->PENDING, PENDING->CONFIRMED


def test_lost_event_is_sent_again_by_the_retry(
    monkeypatch: pytest.MonkeyPatch, events: Events, aws: Any
) -> None:
    order_id = pending()

    def fail(*_: Any) -> None:
        raise RuntimeError("EventBridge down")

    monkeypatch.setattr(orders, "put_event", fail)
    with pytest.raises(RuntimeError):
        confirm(order_id)
    assert stored(aws, order_id)["status"] == "CONFIRMED"  # confirmed, but the ERP was not told
    monkeypatch.setattr(orders, "put_event", lambda _s, kind, detail: events.append((kind, detail)))
    assert confirm(order_id)["status"] == "ALREADY_CONFIRMED"
    assert kinds(events).count("order.confirmed") == 1
    confirm(order_id)
    assert kinds(events).count("order.confirmed") == 1


def test_nothing_is_confirmed_without_the_summary(events: Events, aws: Any) -> None:
    order = draft()
    out = confirm(order["orderId"])
    assert out == {"status": "NOT_CONFIRMABLE", "orderStatus": "DRAFT"}
    assert stored(aws, order["orderId"])["status"] == "DRAFT" and "order.confirmed" not in kinds(
        events
    )


def test_expired_or_cancelled_orders_cannot_be_confirmed(aws: Any) -> None:
    order_id = pending()
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :e",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":e": "EXPIRED"},
    )
    assert confirm(order_id) == {"status": "NOT_CONFIRMABLE", "orderStatus": "EXPIRED"}


def test_confirm_after_the_cutoff_asks_for_a_new_date(clock: Any) -> None:
    order_id = pending()
    clock.now = clock.now.replace(hour=18, minute=5)  # 19:05 Rome: the cut-off for Thursday passed
    out = confirm(order_id)
    assert out["status"] == "NEEDS_FIXES" and out["issues"][0]["code"] == "INVALID_DELIVERY_DATE"


def test_button_must_answer_the_summary_of_this_order(aws: Any) -> None:
    order_id = pending()
    with pytest.raises(ConfirmationMismatchError):  # no summary message recorded
        confirm(order_id, interactiveReply={"contextId": "wamid.FORGED"})
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET summaryMessageId = :m",
        ExpressionAttributeValues={":m": "wamid.SUMMARY"},
    )
    with pytest.raises(ConfirmationMismatchError):  # a button of another message
        confirm(order_id, interactiveReply={"contextId": "wamid.OTHER"})
    assert (
        confirm(order_id, interactiveReply={"contextId": "wamid.SUMMARY"})["status"] == "CONFIRMED"
    )


def test_confirm_of_another_customers_order_is_denied(aws: Any) -> None:
    order_id = pending()
    for who in (OTHER_CUSTOMER, OTHER_REP, STRANGER):
        with pytest.raises(AccessDeniedError):
            confirm(order_id, who)
    assert stored(aws, order_id)["status"] == "PENDING_CONFIRMATION"


def test_rep_confirms_for_the_customer(events: Events, aws: Any) -> None:
    order = draft(REP, "cus_001")
    request_order_confirmation(make(RequestConfirmationInput, caller=REP, orderId=order["orderId"]))
    assert confirm(order["orderId"], REP)["status"] == "CONFIRMED"
    assert stored(aws, order["orderId"])["confirmedBy"] == "rep_001"
    assert [d["createdBy"] for k, d in events if k == "order.confirmed"] == ["rep_001"]


# --- changes and cancel after the confirmation (FN-16) -------------------------------------


def test_confirmed_order_changes_until_the_cutoff(events: Events, aws: Any) -> None:
    order_id = pending()
    confirm(order_id)
    out = update(order_id, ops=[{"op": "update", "lineId": "l2", "quantity": 6}])
    assert out["status"] == "UPDATED" and out["order"]["total"] == Decimal("299.00")
    # T-26b: the updated confirmation goes by email to who confirmed (a flag, not the address)
    assert out["confirmationEmail"] is True
    assert stored(aws, order_id)["revision"] == 1
    assert ("order.updated", {"orderId": order_id, "revision": 1}) in events


def test_confirmed_order_change_without_an_email_says_none_goes_out(aws: Any) -> None:
    no_email = caller("CUSTOMER_CONTACT", "con_003", "conv_3")  # owns cus_003, no email
    order = draft(no_email, customer="cus_003", deliveryDate="2026-10-30")
    request_order_confirmation(
        make(RequestConfirmationInput, caller=no_email, orderId=order["orderId"])
    )
    assert confirm(order["orderId"], no_email)["status"] == "CONFIRMED"
    out = update(order["orderId"], no_email, deliveryNotes="dal retro")
    assert out["status"] == "UPDATED" and out["confirmationEmail"] is False


def test_confirmed_order_change_that_breaks_a_rule_is_not_saved(aws: Any) -> None:
    order_id = pending()
    confirm(order_id)
    out = update(
        order_id,
        ops=[{"op": "update", "lineId": "l1", "quantity": 1}, {"op": "remove", "lineId": "l2"}],
    )
    assert out["status"] == "NEEDS_FIXES" and out["issues"][0]["code"] in {
        "NO_LINES",
        "BELOW_MINIMUM",
    }
    assert (
        len(stored(aws, order_id)["lines"]) == 2
        and stored(aws, order_id)["lines"][0]["quantity"] == 25
    )


def test_after_the_cutoff_the_order_is_locked(clock: Any) -> None:
    order_id = pending()
    confirm(order_id)
    clock.now = clock.now + timedelta(hours=9)  # 19:00 Rome
    with pytest.raises(OrderLockedError):
        update(order_id, ops=[{"op": "update", "lineId": "l1", "quantity": 1}])
    with pytest.raises(OrderLockedError):
        cancel_order(make(CancelOrderInput, caller=CUSTOMER, orderId=order_id))


def test_cancel_draft_pending_and_confirmed(aws: Any, events: Events) -> None:
    for prepare in (
        lambda: draft()["orderId"],
        pending,
        lambda: (lambda i: (confirm(i), i)[1])(pending()),
    ):
        order_id = prepare()
        # the conversation's open draft would be reused: a new conversation per order
        out = cancel_order(make(CancelOrderInput, caller=CUSTOMER, orderId=order_id))
        assert out["status"] == "CANCELLED" and stored(aws, order_id)["status"] == "CANCELLED"
        assert (
            cancel_order(make(CancelOrderInput, caller=CUSTOMER, orderId=order_id))["status"]
            == "CANCELLED"
        )
    assert "order.status_changed" in kinds(events)


def test_scheduled_order_cannot_be_cancelled(aws: Any) -> None:
    order_id = pending()
    confirm(order_id)
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :e",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":e": "SCHEDULED"},
    )
    with pytest.raises(OrderLockedError):
        cancel_order(make(CancelOrderInput, caller=CUSTOMER, orderId=order_id))


def test_cancel_of_another_customers_order_is_denied() -> None:
    order_id = pending()
    with pytest.raises(AccessDeniedError):
        cancel_order(make(CancelOrderInput, caller=OTHER_CUSTOMER, orderId=order_id))


# --- status (FN-17) --------------------------------------------------------------------------


def test_status_of_the_open_orders_of_a_customer(aws: Any) -> None:
    order_id = pending()
    confirm(order_id)
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :e, erpOrderNumber = :n",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":e": "SCHEDULED", ":n": "ERP-1"},
    )
    aws.Table("suppliagent-test-deliveries").put_item(
        Item={"orderId": order_id, "window": "08:00-12:00"}
    )
    out = get_order_status(make(GetOrderStatusInput, caller=CUSTOMER, customerId="cus_001"))
    (entry,) = out["orders"]
    assert entry == {
        "orderId": order_id,
        "status": "SCHEDULED",
        "deliveryDate": THURSDAY,
        "erpOrderNumber": "ERP-1",
        "lines": 2,
        "total": Decimal("256.00"),
        "deliveryWindow": "08:00-12:00",
    }
    one = get_order_status(make(GetOrderStatusInput, caller=REP, orderId=order_id))
    assert one["orders"][0]["orderId"] == order_id


def test_status_needs_exactly_one_selector_and_respects_ownership() -> None:
    order_id = pending()
    with pytest.raises(InvalidInputError):
        get_order_status(make(GetOrderStatusInput, caller=CUSTOMER))
    with pytest.raises(InvalidInputError):
        get_order_status(
            make(GetOrderStatusInput, caller=CUSTOMER, customerId="cus_001", orderId=order_id)
        )
    with pytest.raises(AccessDeniedError):
        get_order_status(make(GetOrderStatusInput, caller=OTHER_CUSTOMER, orderId=order_id))
    with pytest.raises(AccessDeniedError):
        get_order_status(make(GetOrderStatusInput, caller=OTHER_CUSTOMER, customerId="cus_001"))
    with pytest.raises(AccessDeniedError):
        get_order_status(make(GetOrderStatusInput, caller=STRANGER, customerId="cus_001"))


# --- delivery issues (FN-18) -----------------------------------------------------------------


def delivered(aws: Any, status: str = "OUT_FOR_DELIVERY") -> str:
    order_id = pending()
    confirm(order_id)
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :e",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":e": status},
    )
    return order_id


def issue(order_id: str, who: CallerContext = CUSTOMER, **extra: Any) -> dict[str, Any]:
    args = {"type": "MISSING", "lineIds": ["l1"], **extra}
    return report_delivery_issue(
        make(ReportDeliveryIssueInput, caller=who, orderId=order_id, **args)
    )


def test_delivery_issue_is_recorded_with_priority_and_moves_the_order(
    aws: Any, events: Events
) -> None:
    order_id = delivered(aws)
    out = issue(
        order_id,
        type="DAMAGED",
        note="cartone sfondato",
        s3Uris=["s3://media-bucket/media/con_001/m1/photo.jpg"],
    )
    row = aws.Table("suppliagent-test-issues").get_item(Key={"issueId": out["issueId"]})["Item"]
    assert (row["orderId"], row["type"], row["priority"], row["lineIds"]) == (
        order_id,
        "DAMAGED",
        "HIGH",
        ["l1"],
    )
    assert stored(aws, order_id)["status"] == "DELIVERY_ISSUE"
    assert ("delivery.issue_reported", {"orderId": order_id, "type": "DAMAGED"}) in events


def test_issue_after_the_delivery_and_a_second_issue(aws: Any) -> None:
    order_id = delivered(aws, "DELIVERED")
    issue(order_id)
    issue(order_id, type="WRONG", lineIds=["l2"])
    assert stored(aws, order_id)["status"] == "DELIVERY_ISSUE"
    assert len(aws.Table("suppliagent-test-issues").scan()["Items"]) == 2


def test_issue_before_the_delivery_is_refused(aws: Any) -> None:
    order_id = pending()
    confirm(order_id)  # CONFIRMED: nothing delivered
    with pytest.raises(InvalidInputError):
        issue(order_id)


def test_issue_photos_must_be_the_callers_own(aws: Any) -> None:
    order_id = delivered(aws)
    for uri in (
        "s3://media-bucket/media/con_002/m1/photo.jpg",  # someone else's
        "s3://other-bucket/media/con_001/m1/photo.jpg",
        "s3://media-bucket/media/con_001/../con_002/photo.jpg",
        "s3://media-bucket/documents/orders/ord_1.pdf",
    ):
        with pytest.raises(AccessDeniedError):
            issue(order_id, s3Uris=[uri])
    assert stored(aws, order_id)["status"] == "OUT_FOR_DELIVERY"


def test_issue_on_unknown_line_or_foreign_order(aws: Any) -> None:
    order_id = delivered(aws)
    with pytest.raises(InvalidInputError):
        issue(order_id, lineIds=["l9"])
    with pytest.raises(AccessDeniedError):
        issue(order_id, OTHER_CUSTOMER)
    with pytest.raises(AccessDeniedError):
        issue(order_id, STRANGER)


def test_nothing_is_confirmed_in_the_turn_that_produced_the_summary(
    aws: Any, events: Events
) -> None:
    order_id = pending()
    direct = make(ConfirmOrderInput, caller=CUSTOMER, orderId=order_id)
    expected = {
        "status": "NOT_CONFIRMABLE",
        "orderStatus": "PENDING_CONFIRMATION",
        "reason": "NEEDS_CUSTOMER_REPLY",
    }
    assert confirm_order(direct) == expected  # no message after the summary
    reply(aws, direction="OUTBOUND")  # the agent's own messages are not the customer's answer
    reply(aws, conversation="conv_other")  # nor is another conversation
    assert confirm_order(direct) == expected
    assert stored(aws, order_id)["status"] == "PENDING_CONFIRMATION"
    assert "order.confirmed" not in kinds(events)
    reply(aws)
    assert confirm_order(direct)["status"] == "CONFIRMED"


def test_a_message_from_before_the_summary_is_not_an_answer(aws: Any) -> None:
    aws.Table("suppliagent-test-messages").put_item(
        Item={
            "conversationId": "conv_1",
            "tsMessageId": "2026-10-28T08:59:00.000Z#m0",
            "direction": "INBOUND",
        }
    )
    order_id = pending()
    out = confirm_order(make(ConfirmOrderInput, caller=CUSTOMER, orderId=order_id))
    assert out["reason"] == "NEEDS_CUSTOMER_REPLY"


def test_a_line_without_a_price_blocks_the_summary(aws: Any) -> None:
    aws.Table("suppliagent-test-price-lists").delete_item(
        Key={"priceListId": "LIST_STD", "sku": "FARINA-00-25KG"}
    )
    order = draft()
    assert [ln.get("unitPrice") for ln in order["lines"]][1] is None
    issue = issues_of(order["orderId"])["NO_PRICE"]
    assert issue["lineIds"] == ["l2"]
    update(
        order["orderId"],
        ops=[{"op": "remove", "lineId": "l2"}, {"op": "add", "sku": "OLIO-EVO-5L", "quantity": 4}],
    )
    out = request_order_confirmation(
        make(RequestConfirmationInput, caller=CUSTOMER, orderId=order["orderId"])
    )
    assert out["status"] == "PENDING_CONFIRMATION"


def test_summary_says_where_the_confirmation_email_goes(aws: Any) -> None:  # F-07.C7
    order_id = pending()  # con_001 has a verified email identity
    again = request_order_confirmation(
        make(RequestConfirmationInput, caller=CUSTOMER, orderId=order_id)
    )
    assert again["orderEmail"] == "ordini.fornoantico@example.com"

    no_email = caller("CUSTOMER_CONTACT", "con_003", "conv_3")  # owns cus_003, no email
    order = draft(no_email, customer="cus_003", deliveryDate="2026-10-30")  # a Friday
    out = request_order_confirmation(
        make(RequestConfirmationInput, caller=no_email, orderId=order["orderId"])
    )
    assert out["status"] == "PENDING_CONFIRMATION" and out["orderEmail"] is None
