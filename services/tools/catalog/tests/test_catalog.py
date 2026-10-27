"""match_products / search_catalog: classification, history, "il solito", authorization (FN-07)."""

from types import SimpleNamespace
from typing import Any

import pytest
from catalog_helpers import FakeVectors
from suppliagent_shared.auth import CallerContext
from suppliagent_shared.errors import AccessDeniedError
from suppliagent_shared.models import Role
from suppliagent_tool_catalog.catalog import (
    MatchProductsInput,
    SearchCatalogInput,
    match_products,
    search_catalog,
)
from suppliagent_tool_catalog.handler import lambda_handler


def caller(
    role: Role, contact: str | None = None, conversation: str | None = None
) -> CallerContext:
    return CallerContext.model_validate(
        {
            "role": role,
            "contactId": contact,
            "channelAddress": "WHATSAPP#+39",
            "conversationId": conversation,
        }
    )


CALLER = caller(Role.CUSTOMER_CONTACT, "con_t1", "c1")


def match_as(
    who: CallerContext, text: str, customer: str, unit: str | None = None
) -> dict[str, Any]:
    args = {"caller": who.model_dump(), "rawText": text, "customerId": customer, "rawUnit": unit}
    return match_products(MatchProductsInput.model_validate(args))


def match(text: str, customer: str = "cus_t1", unit: str | None = None) -> dict[str, Any]:
    return match_as(CALLER, text, customer, unit)


def test_clear_match_is_matched_and_emits_an_event(
    vectors: FakeVectors, history: Any, events: list[Any]
) -> None:
    history("cus_t1", [])
    vectors.hits = [("FARINA-00-25KG", 0.9), ("FDL-PIZZA-1KG", 0.4)]
    result = match("farina 00 25 kg")
    assert result["status"] == "MATCHED"
    assert result["candidates"][0]["sku"] == "FARINA-00-25KG"
    assert events == [
        (
            "order.line_matched",
            {
                "conversationId": "c1",
                "status": "MATCHED",
                "confidence": result["candidates"][0]["confidence"],
            },
        )
    ]


def test_unrelated_text_is_unmatched(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [])
    vectors.hits = [("FARINA-00-25KG", 0.35)]
    result = match("zzzzqqq")
    assert result["status"] == "UNMATCHED"


def test_close_candidates_are_ambiguous_with_at_most_three(
    vectors: FakeVectors, history: Any
) -> None:
    history("cus_t1", [])
    vectors.hits = [("FDL-PIZZA-1KG", 0.9), ("FDL-PIZZA-2KG", 0.9), ("BUFALA-250", 0.88)]
    result = match("fior di latte per pizza")
    assert result["status"] == "AMBIGUOUS"
    assert len(result["candidates"]) <= 3


def test_previously_bought_candidate_comes_first(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [["FDL-PIZZA-2KG"]])
    vectors.hits = [("FDL-PIZZA-1KG", 0.9), ("FDL-PIZZA-2KG", 0.9)]
    result = match("fior di latte per pizza")
    assert [c["sku"] for c in result["candidates"][:2]] == ["FDL-PIZZA-2KG", "FDL-PIZZA-1KG"]
    assert result["candidates"][0]["purchasedBefore"] is True


def test_abbreviation_found_through_history_even_without_a_vector_hit(
    vectors: FakeVectors, history: Any
) -> None:
    history("cus_t1", [["FARINA-00-25KG"]])
    vectors.hits = []
    result = match("farina 00")
    assert result["candidates"][0]["sku"] == "FARINA-00-25KG"


def test_il_solito_resolves_from_history(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [["FDL-PIZZA-1KG"], ["FDL-PIZZA-1KG"], ["FDL-PIZZA-2KG"]])
    vectors.hits = [("FDL-PIZZA-1KG", 0.8), ("FDL-PIZZA-2KG", 0.8), ("BUFALA-250", 0.8)]
    result = match("il solito mozzarella")
    assert result["usual"] is True
    assert result["status"] == "MATCHED"
    assert result["candidates"][0]["sku"] == "FDL-PIZZA-1KG"


def test_il_solito_with_an_unsettled_history_asks(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [["FDL-PIZZA-1KG", "FDL-PIZZA-2KG"], ["FDL-PIZZA-1KG", "FDL-PIZZA-2KG"]])
    vectors.hits = [("FDL-PIZZA-1KG", 0.9), ("FDL-PIZZA-2KG", 0.9)]
    assert match("il solito mozzarella")["status"] == "AMBIGUOUS"


def test_il_solito_with_nothing_in_the_history_asks(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [])
    vectors.hits = [("FARINA-00-25KG", 0.95)]
    assert match("il solito farina 00")["status"] == "AMBIGUOUS"


def test_discontinued_product_is_never_auto_matched_and_shows_substitutes(
    vectors: FakeVectors, history: Any, aws: Any
) -> None:
    history("cus_t1", [])
    aws.Table("suppliagent-test-stock").put_item(
        Item={"sku": "OLD-BURRO", "substitutes": ["BURRO-2"]}
    )
    vectors.hits = [("OLD-BURRO", 0.95)]
    lead = match("burro panetto 1 kg")["candidates"][0]
    assert lead["discontinued"] and lead["substitutes"] == ["BURRO-2"]
    assert lead["confidence"] < 0.85


def test_incompatible_unit_lowers_the_confidence(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [])
    vectors.hits = [("FARINA-00-25KG", 0.8)]
    same = match("farina 00", unit="pz")["candidates"][0]["confidence"]
    other = match("farina 00", unit="lt")["candidates"][0]["confidence"]
    assert other < same


def test_customer_of_someone_else_is_denied(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [])
    with pytest.raises(AccessDeniedError):
        match("farina", customer="cus_other")


def test_unknown_role_and_pending_contact_are_denied(history: Any, aws: Any) -> None:
    history("cus_t1", [])
    aws.Table("suppliagent-test-contacts").put_item(
        Item={"contactId": "con_p", "customerIds": ["cus_t1"], "status": "PENDING_VERIFICATION"}
    )
    for who in (
        caller(Role.UNKNOWN),
        caller(Role.CUSTOMER_CONTACT, "con_p"),
    ):
        with pytest.raises(AccessDeniedError):
            match_as(who, "farina", "cus_t1")


def test_rep_reaches_only_their_portfolio(vectors: FakeVectors, history: Any, aws: Any) -> None:
    history("cus_t1", [])
    aws.Table("suppliagent-test-customers").put_item(
        Item={"customerId": "cus_t1", "repId": "rep_a"}
    )
    vectors.hits = [("FARINA-00-25KG", 0.9)]

    ok = match_as(caller(Role.SALES_REP, "rep_a"), "farina 00", "cus_t1")
    assert ok["candidates"]
    with pytest.raises(AccessDeniedError):
        match_as(caller(Role.SALES_REP, "rep_b"), "farina", "cus_t1")


def test_search_catalog_returns_active_products_and_filters_by_category(
    vectors: FakeVectors, history: Any
) -> None:
    history("cus_t1", [])
    vectors.hits = [("BUFALA-250", 0.9), ("OLD-BURRO", 0.9)]
    result = search_catalog(
        SearchCatalogInput.model_validate(
            {"caller": CALLER.model_dump(), "query": "bufala", "category": "latticini"}
        )
    )
    assert [r["sku"] for r in result["results"]] == ["BUFALA-250"]
    assert vectors.calls[0]["filter"] == {"category": "latticini"}


def test_search_catalog_is_denied_to_unverified_callers(history: Any) -> None:
    with pytest.raises(AccessDeniedError):
        search_catalog(
            SearchCatalogInput.model_validate(
                {"caller": caller(Role.UNKNOWN).model_dump(), "query": "x"}
            )
        )


CONTEXT = SimpleNamespace(
    client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": "catalog___match_products"}),
    function_name="tool-catalog",
    memory_limit_in_mb=512,
    invoked_function_arn="arn:aws:lambda:eu-west-1:111111111111:function:x",
    aws_request_id="r1",
)


def test_handler_maps_errors_to_codes_only(vectors: FakeVectors, history: Any) -> None:
    history("cus_t1", [])
    caller = CALLER.model_dump(exclude_none=True)
    denied = lambda_handler({"caller": caller, "rawText": "farina", "customerId": "cus_x"}, CONTEXT)
    assert denied == {"error": "ACCESS_DENIED"}
    assert lambda_handler({"caller": caller, "rawText": ""}, CONTEXT) == {"error": "INVALID_INPUT"}
    vectors.hits = [("FARINA-00-25KG", 0.9)]
    ok = lambda_handler({"caller": caller, "rawText": "farina 00", "customerId": "cus_t1"}, CONTEXT)
    assert ok["status"] in {"MATCHED", "AMBIGUOUS"}
