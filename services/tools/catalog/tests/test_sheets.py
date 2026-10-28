"""ask_product_sheets (T-44b, FN-21): passages with the sheet to cite, NOT_FOUND, authorization."""

from types import SimpleNamespace
from typing import Any

import pytest
from suppliagent_shared.auth import CallerContext
from suppliagent_shared.errors import AccessDeniedError
from suppliagent_shared.models import Role
from suppliagent_tool_catalog import sheets
from suppliagent_tool_catalog.handler import lambda_handler
from suppliagent_tool_catalog.sheets import AskProductSheetsInput, ask_product_sheets


def caller(role: Role, contact: str | None = None) -> CallerContext:
    return CallerContext.model_validate(
        {
            "role": role,
            "contactId": contact,
            "channelAddress": "WHATSAPP#+39",
            "conversationId": "c1",
        }
    )


CUSTOMER = caller(Role.CUSTOMER_CONTACT, "con_001")


class FakeKb:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []

    def retrieve(self, **request: Any) -> dict[str, Any]:
        self.calls.append(request)
        return {"retrievalResults": self.results}


def hit(sku: str, score: float, text: str = "## Allergeni\nLatte e derivati") -> dict[str, Any]:
    return {
        "content": {"text": text},
        "score": score,
        "metadata": {"sku": sku, "category": "latticini"},
        "location": {"s3Location": {"uri": f"s3://bucket/sheets/{sku}.md"}},
    }


@pytest.fixture(autouse=True)
def kb(monkeypatch: pytest.MonkeyPatch) -> FakeKb:
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KB12345678")
    fake = FakeKb()
    monkeypatch.setattr(sheets, "_kb", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def rep_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(sheets, "put_event", lambda _s, kind, detail: sent.append((kind, detail)))
    return sent


def ask(question: str, sku: str | None = None, who: CallerContext = CUSTOMER) -> dict[str, Any]:
    args = {"caller": who.model_dump(), "question": question, "sku": sku}
    return ask_product_sheets(AskProductSheetsInput.model_validate(args))


def test_passages_come_with_the_sheet_to_cite(kb: FakeKb) -> None:
    kb.results = [hit("FDL-PIZZA-1KG", 0.81), hit("FDL-PIZZA-2KG", 0.61)]
    result = ask("Il fior di latte contiene lattosio?")

    assert result["status"] == "FOUND"
    [passage] = result["passages"]  # the weak hit is dropped
    assert passage["sku"] == "FDL-PIZZA-1KG"
    assert passage["sheet"] == "Scheda tecnica – Fior di latte per pizza 1 kg"
    assert "Latte e derivati" in passage["text"] and passage["score"] == 0.81
    [call] = kb.calls
    assert call["knowledgeBaseId"] == "KB12345678"
    assert "filter" not in call["retrievalConfiguration"]["vectorSearchConfiguration"]


def test_with_the_sku_a_short_question_still_finds_the_sheet(kb: FakeKb) -> None:
    kb.results = [hit("BURRATA-125", 0.51)]  # "lattosio" on the burrata sheet, measured
    assert ask("lattosio", sku="BURRATA-125")["status"] == "FOUND"
    assert ask("lattosio")["status"] == "NOT_FOUND"  # without the sku the bar stays high
    kb.results = [hit("BURRATA-125", 0.3)]
    assert ask("orari del magazzino", sku="BURRATA-125")["status"] == "NOT_FOUND"


def test_a_known_sku_filters_the_search(kb: FakeKb) -> None:
    kb.results = [hit("FDL-PIZZA-1KG", 0.7)]
    ask("conservazione", sku="FDL-PIZZA-1KG")
    search = kb.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert search["filter"] == {"equals": {"key": "sku", "value": "FDL-PIZZA-1KG"}}


def test_nothing_close_enough_is_not_found(kb: FakeKb) -> None:
    kb.results = [hit("FDL-PIZZA-1KG", 0.3)]
    assert ask("Quanti dipendenti ha il caseificio?") == {"status": "NOT_FOUND", "passages": []}
    kb.results = []
    assert ask("origine del tartufo")["status"] == "NOT_FOUND"


def test_unknown_and_pending_callers_are_denied(aws: Any) -> None:
    aws.Table("suppliagent-test-contacts").put_item(
        Item={"contactId": "con_p", "customerIds": ["cus_001"], "status": "PENDING_VERIFICATION"}
    )
    for who in (caller(Role.UNKNOWN), caller(Role.CUSTOMER_CONTACT, "con_p")):
        with pytest.raises(AccessDeniedError):
            ask("allergeni della burrata", who=who)


def test_a_sales_rep_gets_the_sheets_and_the_query_is_counted(
    kb: FakeKb, rep_events: list[Any]
) -> None:
    kb.results = [hit("FDL-PIZZA-1KG", 0.8)]
    assert ask("allergeni", who=caller(Role.SALES_REP, "rep_001"))["status"] == "FOUND"
    assert rep_events == [("rep.query", {"repId": "rep_001", "type": "sheets"})]
    ask("allergeni")  # a customer contact: no rep event
    assert len(rep_events) == 1


def test_an_invalid_sku_is_refused_by_the_handler(kb: FakeKb) -> None:
    context = SimpleNamespace(
        client_context=SimpleNamespace(
            custom={"bedrockAgentCoreToolName": "catalog___ask_product_sheets"}
        )
    )
    event = {"caller": CUSTOMER.model_dump(), "question": "allergeni", "sku": "drop table"}
    assert lambda_handler(event, context) == {"error": "INVALID_INPUT"}
    assert kb.calls == []


def test_a_lowercase_sku_is_accepted(kb: FakeKb) -> None:
    kb.results = [hit("FDL-PIZZA-1KG", 0.7)]
    ask("allergeni", sku=" fdl-pizza-1kg ")
    search = kb.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert search["filter"]["equals"]["value"] == "FDL-PIZZA-1KG"
