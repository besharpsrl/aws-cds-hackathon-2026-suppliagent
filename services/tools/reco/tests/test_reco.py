"""FN-11 / FN-20 acceptance: one motivated suggestion per order with consent, rep briefing,
refusal kept, accepted value tracked, role-based access (negative tests)."""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from suppliagent_shared.auth import CallerContext
from suppliagent_shared.errors import AccessDeniedError
from suppliagent_tool_reco.handler import lambda_handler
from suppliagent_tool_reco.reco import (
    OutcomeInput,
    RecommendInput,
    recommend_products,
    record_suggestion_outcome,
)


def make[T: BaseModel](cls: type[T], **kwargs: Any) -> T:
    """Validated model from plain values (the Gateway sends JSON, not typed objects)."""
    return cls.model_validate(kwargs)


def caller(role: str, contact: str | None) -> CallerContext:
    return make(
        CallerContext,
        role=role,
        contactId=contact,
        channelAddress="WHATSAPP#+39333",
        conversationId="conv_1",
    )


LUCA = caller("CUSTOMER_CONTACT", "con_001")  # cus_001, cus_005; proactive consent given
NO_CONSENT = caller("CUSTOMER_CONTACT", "con_002")  # cus_002; consent refused
NEVER_ASKED = caller("CUSTOMER_CONTACT", "con_003")  # cus_003; consent never asked
REP = caller("SALES_REP", "rep_001")  # cus_001, cus_002, cus_003
OTHER_REP = caller("SALES_REP", "rep_002")
STRANGER = caller("UNKNOWN", None)


def line(
    n: int, sku: str, quantity: int, total: str = "10.00", status: str = "MATCHED"
) -> dict[str, Any]:
    return {
        "lineId": f"l{n}",
        "status": status,
        "sku": sku,
        "quantity": Decimal(quantity),
        "lineTotal": Decimal(total),
    }


def put_order(aws: Any, order_id: str, customer: str, *lines: dict[str, Any], **extra: Any) -> None:
    aws.Table("suppliagent-test-orders").put_item(
        Item={
            "orderId": order_id,
            "customerId": customer,
            "status": "DRAFT",
            "createdAt": "2026-10-28T08:55:00.000Z",
            "deliveryDate": "2026-10-29",
            "lines": list(lines),
            **extra,
        }
    )


def order_of(aws: Any, order_id: str) -> dict[str, Any]:
    item: dict[str, Any] = aws.Table("suppliagent-test-orders").get_item(Key={"orderId": order_id})[
        "Item"
    ]
    return item


def recommend(who: CallerContext, **target: str) -> dict[str, Any]:
    return recommend_products(make(RecommendInput, caller=who, **target))


def outcome(who: CallerContext, order_id: str, accepted: bool) -> dict[str, Any]:
    return record_suggestion_outcome(
        make(OutcomeInput, caller=who, orderId=order_id, accepted=accepted)
    )


@pytest.fixture
def luca_order(aws: Any) -> str:
    """cus_001 orders fior di latte, pelati and burrata: the flour (every 14 days) is forgotten."""
    put_order(
        aws,
        "ord_a1",
        "cus_001",
        line(1, "FDL-PIZZA-1KG", 25),
        line(2, "POM-PELATI-2500", 2),
        line(3, "BURRATA-125", 15),
    )
    return "ord_a1"


# --- one suggestion per order (FN-11, F-07.C1) ---------------------------------------------


def test_forgotten_usual_product_is_suggested_with_its_reason(aws: Any, luca_order: str) -> None:
    result = recommend(LUCA, orderId=luca_order)
    assert result["status"] == "OK"
    [suggestion] = result["suggestions"]
    assert suggestion["sku"] == "FARINA-00-25KG"
    assert suggestion["reason"] == "REORDER_DUE"
    assert suggestion["everyDays"] == 14
    assert suggestion["lastOrderedAt"] == "2026-09-28T09:00:00Z"
    assert suggestion["lastQuantity"] == 6
    assert suggestion["name"] and suggestion["finalPrice"] > 0
    assert order_of(aws, luca_order)["suggestion"]["sku"] == "FARINA-00-25KG"


def test_at_most_one_suggestion_per_order(luca_order: str) -> None:
    recommend(LUCA, orderId=luca_order)
    again = recommend(LUCA, orderId=luca_order)
    assert again == {
        "status": "NONE",
        "reason": "ALREADY_SUGGESTED",
        "suggestions": [],
        "orderId": luca_order,
    }


@pytest.mark.parametrize("who", [NO_CONSENT, NEVER_ASKED], ids=["refused", "never-asked"])
def test_no_suggestion_without_proactive_consent(aws: Any, who: CallerContext) -> None:
    customer = "cus_002" if who is NO_CONSENT else "cus_003"
    put_order(aws, "ord_c1", customer, line(1, "POM-PELATI-2500", 2))
    result = recommend(who, orderId="ord_c1")
    assert result["reason"] == "NO_CONSENT"
    assert "suggestion" not in order_of(aws, "ord_c1")


def test_out_of_stock_skipped_then_promotion(aws: Any) -> None:
    """Everything due is in the order; the similar venues' product is out of stock: promotion."""
    put_order(
        aws,
        "ord_p1",
        "cus_001",
        *(
            line(i, sku, 1)
            for i, sku in enumerate(
                ["FDL-PIZZA-1KG", "FARINA-00-25KG", "POM-PELATI-2500", "BURRATA-125"], 1
            )
        ),
    )
    [suggestion] = recommend(LUCA, orderId="ord_p1")["suggestions"]
    assert suggestion["reason"] == "PROMOTION"
    assert suggestion["sku"] == "PARM-REGG-KG"
    assert suggestion["promo"]["promoPrice"] == Decimal("15.2")
    assert suggestion["promo"]["validTo"] == "2026-11-15"


def test_closed_order_gets_no_suggestion(aws: Any) -> None:
    put_order(aws, "ord_x1", "cus_001", line(1, "FDL-PIZZA-1KG", 25), status="CONFIRMED")
    assert recommend(LUCA, orderId="ord_x1")["reason"] == "ORDER_CLOSED"


def test_customer_needs_an_order(aws: Any) -> None:
    assert recommend(LUCA, customerId="cus_001")["reason"] == "ORDER_REQUIRED"


def test_rep_order_gets_one_suggestion_too(aws: Any, luca_order: str) -> None:
    result = recommend(REP, orderId=luca_order)
    assert [s["sku"] for s in result["suggestions"]] == ["FARINA-00-25KG"]
    assert order_of(aws, luca_order)["suggestion"]["suggestedBy"] == "rep_001"


# --- outcome: refusal kept, accepted value tracked (F-07.C2, FN-11) -------------------------


def test_refusal_is_recorded_and_not_proposed_again(
    aws: Any, luca_order: str, events: list[tuple[str, dict[str, Any]]]
) -> None:
    recommend(LUCA, orderId=luca_order)
    result = outcome(LUCA, luca_order, accepted=False)
    assert result == {"status": "RECORDED", "orderId": luca_order, "accepted": False}
    assert order_of(aws, luca_order)["suggestion"]["accepted"] is False
    assert events == [
        (
            "order.suggestion",
            {
                "orderId": luca_order,
                "sku": "FARINA-00-25KG",
                "reason": "REORDER_DUE",
                "accepted": False,
                "value": None,
            },
        )
    ]
    insights = aws.Table("suppliagent-test-customer-insights").get_item(
        Key={"customerId": "cus_001"}
    )["Item"]
    assert insights["rejectedSuggestions"][0]["sku"] == "FARINA-00-25KG"
    assert insights["expectedReorders"]  # the analyzer's data is untouched

    put_order(aws, "ord_a2", "cus_001", line(1, "POM-PELATI-2500", 2), line(2, "BURRATA-125", 1))
    [next_one] = recommend(LUCA, orderId="ord_a2")["suggestions"]
    assert next_one["sku"] == "FDL-PIZZA-1KG"  # the next due product, not the flour again


def test_accepted_suggestion_tracks_its_value(
    aws: Any, luca_order: str, events: list[tuple[str, dict[str, Any]]]
) -> None:
    recommend(LUCA, orderId=luca_order)
    order = order_of(aws, luca_order)
    order["lines"].append(line(4, "FARINA-00-25KG", 6, total="171.00"))
    aws.Table("suppliagent-test-orders").put_item(Item=order)  # the customer said yes
    result = outcome(LUCA, luca_order, accepted=True)
    assert result["value"] == Decimal("171.00")
    assert order_of(aws, luca_order)["suggestion"]["value"] == Decimal("171.00")
    assert events[-1][1]["accepted"] is True and events[-1][1]["value"] == 171.0
    assert outcome(LUCA, luca_order, accepted=False)["status"] == "ALREADY_RECORDED"
    assert len(events) == 1


def test_outcome_without_suggestion(luca_order: str) -> None:
    assert outcome(LUCA, luca_order, accepted=True)["status"] == "NO_SUGGESTION"


# --- sales rep briefing (FN-20, F-10.A) -----------------------------------------------------


def test_briefing_gives_three_motivated_proposals_of_different_kinds() -> None:
    result = recommend(REP, customerId="cus_002")
    picked = [(s["reason"], s["sku"]) for s in result["suggestions"]]
    # buffalo mozzarella is due first but out of stock; grated grana, oil and pelati are due next
    assert picked == [
        ("REORDER_DUE", "GRANA-GRAT-1KG"),
        ("DROPPED", "PROSC-COTTO-KG"),
        ("SIMILAR_VENUES", "BURRATA-125"),
    ]
    similar = result["suggestions"][2]
    assert similar["note"] == "Abbinata spesso a mozzarella di bufala da locali simili"


def test_briefing_without_insights_still_has_promotions(aws: Any) -> None:
    aws.Table("suppliagent-test-customer-insights").delete_item(Key={"customerId": "cus_003"})
    result = recommend(REP, customerId="cus_003")
    assert {s["reason"] for s in result["suggestions"]} == {"PROMOTION"}


# --- authorization (negative tests) ----------------------------------------------------------


def test_customer_cannot_use_another_customers_order(luca_order: str) -> None:
    with pytest.raises(AccessDeniedError):
        recommend(NO_CONSENT, orderId=luca_order)
    with pytest.raises(AccessDeniedError):
        outcome(NO_CONSENT, luca_order, accepted=True)


def test_rep_outside_portfolio_is_denied(luca_order: str) -> None:
    with pytest.raises(AccessDeniedError):
        recommend(OTHER_REP, customerId="cus_001")
    with pytest.raises(AccessDeniedError):
        recommend(OTHER_REP, orderId=luca_order)


def test_customer_cannot_get_a_briefing_of_another_venue() -> None:
    with pytest.raises(AccessDeniedError):
        recommend(LUCA, customerId="cus_002")


def test_unknown_caller_and_unknown_order_are_denied() -> None:
    with pytest.raises(AccessDeniedError):
        recommend(STRANGER, customerId="cus_001")
    with pytest.raises(AccessDeniedError):
        recommend(LUCA, orderId="ord_missing")


def test_exactly_one_target() -> None:
    with pytest.raises(ValidationError):
        make(RecommendInput, caller=REP, customerId="cus_001", orderId="ord_a1")
    with pytest.raises(ValidationError):
        make(RecommendInput, caller=REP)


# --- Lambda entry point -----------------------------------------------------------------------


def invoke(tool: str, event: dict[str, Any]) -> dict[str, Any]:
    context = SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"reco___{tool}"})
    )
    return lambda_handler(event, context)


def test_handler_returns_plain_json(luca_order: str) -> None:
    result = invoke(
        "recommend_products", {"caller": LUCA.model_dump(mode="json"), "orderId": luca_order}
    )
    assert json.loads(json.dumps(result)) == result
    assert result["suggestions"][0]["lastQuantity"] == 6


def test_handler_maps_errors() -> None:
    who = LUCA.model_dump(mode="json")
    assert invoke("recommend_products", {"caller": who})["error"] == "INVALID_INPUT"
    assert invoke("recommend_products", {"caller": who, "customerId": "cus_004"}) == {
        "error": "ACCESS_DENIED"
    }
    assert invoke("nope", {"caller": who}) == {"error": "UNKNOWN_TOOL"}
