"""Seed data (T-04 core): valid models, consistent references, loadable into DynamoDB."""

import importlib.util
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
import pytest
from moto import mock_aws

SEED_PY = Path(__file__).parents[1] / "seed" / "seed.py"
KEYS = {
    "customers": ("customerId",),
    "contacts": ("contactId",),
    "channel-identities": ("channelAddress",),
    "sales-reps": ("repId",),
    "order-history": ("customerId", "dateOrderId"),
    "customer-insights": ("customerId",),
    "products": ("sku",),
    "price-lists": ("priceListId", "sku"),
    "promotions": ("promoId",),
    "stock": ("sku",),
    "delivery-calendar": ("zone", "date"),
}


def _import_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_script", SEED_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _import_seed()
DATA: dict[str, list[dict[str, Any]]] = seed.load()


def ids(stem: str, key: str) -> set[str]:
    return {item[key] for item in DATA[stem]}


def test_every_table_has_data_and_unique_keys() -> None:
    assert DATA.keys() == KEYS.keys()
    for stem, key in KEYS.items():
        keys = Counter(tuple(item[k] for k in key) for item in DATA[stem])
        assert DATA[stem], stem
        assert max(keys.values()) == 1, f"duplicate key in {stem}"


def test_references_are_consistent() -> None:
    customers, reps = ids("customers", "customerId"), ids("sales-reps", "repId")
    contacts = ids("contacts", "contactId")
    assert {c["repId"] for c in DATA["customers"]} <= reps
    for contact in DATA["contacts"]:
        assert contact["customerId"] in contact["customerIds"]
        assert set(contact["customerIds"]) <= customers
    for identity in DATA["channel-identities"]:
        expected = "SALES_REP" if identity["contactId"].startswith("rep_") else "CUSTOMER_CONTACT"
        assert identity["role"] == expected
        assert identity["contactId"] in contacts | reps
        assert identity["channelAddress"].startswith(identity["channel"] + "#")
    assert ids("order-history", "customerId") == customers
    assert ids("customer-insights", "customerId") <= customers


def test_insights_only_reference_products_the_customer_bought() -> None:
    bought: dict[str, set[str]] = {}
    for order in DATA["order-history"]:
        bought.setdefault(order["customerId"], set()).update(li["sku"] for li in order["lines"])
    for ins in DATA["customer-insights"]:
        skus = {r["sku"] for r in ins["expectedReorders"]} | set(ins["droppedProducts"])
        assert skus <= bought[ins["customerId"]]


def test_demo_scenarios_are_covered() -> None:
    """Fixtures the agent flows and the authorization tests rely on."""
    rep_of = {c["customerId"]: c["repId"] for c in DATA["customers"]}
    multi = [c for c in DATA["contacts"] if len(c["customerIds"]) > 1]
    assert any(len({rep_of[cid] for cid in c["customerIds"]}) > 1 for c in multi)  # F-02.C5
    assert any(c["language"] == "en" for c in DATA["contacts"])  # FN-27
    assert any("privacyNoticeSentAt" not in c for c in DATA["contacts"])  # F-01 first contact
    assert any(ins["droppedProducts"] for ins in DATA["customer-insights"])
    # T-71: judges identify with test customers published in the README, verified at once
    demo = [c["customerCode"] for c in DATA["customers"] if c["autoVerifyContacts"]]
    assert demo == ["C90001", "C90002", "C90003"]
    assert any(
        r["dueAt"] < ins["updatedAt"]
        for ins in DATA["customer-insights"]
        for r in ins["expectedReorders"]
    )  # overdue reorder, F-13


def test_catalog_covers_history_prices_and_stock() -> None:
    skus = ids("products", "sku")
    bought = {li["sku"] for order in DATA["order-history"] for li in order["lines"]}
    assert bought <= skus  # every SKU of the history is in the catalog
    assert ids("stock", "sku") == skus
    assert {p["sku"] for p in DATA["promotions"]} <= skus
    for list_id in {c["priceListId"] for c in DATA["customers"]}:
        assert {p["sku"] for p in DATA["price-lists"] if p["priceListId"] == list_id} == skus
    for item in DATA["stock"]:
        assert set(item["substitutes"]) <= skus
    zones = {c["zone"] for c in DATA["customers"]}
    assert {e["zone"] for e in DATA["delivery-calendar"]} <= zones


def test_catalog_scenarios_are_covered() -> None:
    """Fixtures of F-06: out of stock with a substitute, partial stock, pack multiple, retired."""
    stock = {i["sku"]: i for i in DATA["stock"]}
    products = {p["sku"]: p for p in DATA["products"]}
    assert any(i["quantity"] == 0 and i["substitutes"] for i in DATA["stock"])  # C2
    assert any(0 < i["quantity"] < 10 for i in DATA["stock"])  # C3
    assert any(p.get("multiple", 1) > 1 for p in DATA["products"])  # C4
    assert any(not p.get("active", True) for p in DATA["products"])  # retired, F-05.C6
    assert all(
        products[s]["active"] if "active" in products[s] else True
        for i in stock.values()
        for s in i["substitutes"][:1]
    )  # best substitute is sold


@pytest.fixture
def dynamodb() -> Any:
    with mock_aws():
        resource: Any = boto3.resource("dynamodb", region_name="eu-west-1")
        for stem, key in KEYS.items():
            resource.create_table(
                TableName=f"suppliagent-dev-{stem}",
                KeySchema=[{"AttributeName": key[0], "KeyType": "HASH"}]
                + [{"AttributeName": k, "KeyType": "RANGE"} for k in key[1:]],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in key],
                BillingMode="PAY_PER_REQUEST",
            )
        yield resource


def test_reset_clears_orders_that_exist(dynamodb: Any) -> None:
    for table, key in [("orders", "orderId"), ("deliveries", "orderId"), ("issues", "issueId")]:
        dynamodb.create_table(
            TableName=f"suppliagent-dev-{table}",
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.Table(f"suppliagent-dev-{table}").put_item(Item={key: f"{table}_1"})
    spec = importlib.util.spec_from_file_location("reset_script", SEED_PY.with_name("reset.py"))
    assert spec and spec.loader
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)
    reset.clear(dynamodb, "dev")
    for table in ("orders", "deliveries", "issues"):
        assert dynamodb.Table(f"suppliagent-dev-{table}").scan()["Count"] == 0


def test_reset_releases_handed_off_conversations(dynamodb: Any) -> None:  # F-14, until T-63
    conversations = dynamodb.create_table(
        TableName="suppliagent-dev-conversations",
        KeySchema=[{"AttributeName": "conversationId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "conversationId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    conversations.put_item(
        Item={"conversationId": "conv_h", "mode": "HUMAN", "handoff": {"reason": "X"}}
    )
    conversations.put_item(Item={"conversationId": "conv_a", "mode": "AGENT", "role": "UNKNOWN"})
    spec = importlib.util.spec_from_file_location("reset_script", SEED_PY.with_name("reset.py"))
    assert spec and spec.loader
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)
    assert reset.release_handoffs(dynamodb, "dev") == 1
    released = conversations.get_item(Key={"conversationId": "conv_h"})["Item"]
    assert released == {"conversationId": "conv_h", "mode": "AGENT"}
    untouched = conversations.get_item(Key={"conversationId": "conv_a"})["Item"]
    assert untouched["role"] == "UNKNOWN"


def test_write_loads_every_item(dynamodb: Any) -> None:
    seed.write(dynamodb, "dev", DATA)
    seed.write(dynamodb, "dev", DATA)  # idempotent: same items, no duplicates
    for stem, items in DATA.items():
        assert dynamodb.Table(f"suppliagent-dev-{stem}").scan()["Count"] == len(items)


def test_every_technical_sheet_has_its_metadata_for_an_existing_product() -> None:
    """T-06b: `<sku>.md` + `<sku>.md.metadata.json` (Bedrock sidecar, filters sku and category)."""
    import json

    products = {p["sku"]: p for p in DATA["products"]}
    files = seed.sheet_files()
    sheets = [p for p in files if p.suffix == ".md"]
    assert len(sheets) >= 10 and len(files) == 2 * len(sheets)
    for sheet in sheets:
        sku = sheet.stem
        meta = json.loads(sheet.with_name(sheet.name + ".metadata.json").read_text())
        assert meta == {"metadataAttributes": {"sku": sku, "category": products[sku]["category"]}}
        text = sheet.read_text(encoding="utf-8")
        assert f"**Codice (SKU)**: {sku}" in text and "## Allergeni" in text
        assert "sintetica" in text  # synthetic demo data, never a real producer's sheet


def test_sheets_are_uploaded_and_the_ingestion_started(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    started: list[dict[str, Any]] = []

    class FakeAgent:
        def start_ingestion_job(self, **request: Any) -> dict[str, Any]:
            started.append(request)
            return {"ingestionJob": {"ingestionJobId": "job-1"}}

    with mock_aws():
        session = boto3.Session(region_name="eu-west-1")
        account = session.client("sts").get_caller_identity()["Account"]
        bucket = f"suppliagent-dev-catalog-assets-{account}"
        session.client("s3").create_bucket(
            Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
        )
        ssm = session.client("ssm")
        ssm.put_parameter(Name="/suppliagent/dev/productSheetsKbId", Value="KB1", Type="String")
        ssm.put_parameter(
            Name="/suppliagent/dev/productSheetsDataSourceId", Value="DS1", Type="String"
        )
        real_client: Any = session.client

        def client(name: str, **kwargs: Any) -> Any:
            return FakeAgent() if name == "bedrock-agent" else real_client(name, **kwargs)

        monkeypatch.setattr(session, "client", client)
        assert seed.upload_sheets(session, "dev") == "job-1"
        keys = {o["Key"] for o in real_client("s3").list_objects_v2(Bucket=bucket)["Contents"]}
    assert "sheets/BURRATA-125.md" in keys and "sheets/BURRATA-125.md.metadata.json" in keys
    assert started == [{"knowledgeBaseId": "KB1", "dataSourceId": "DS1"}]


def test_an_ingestion_already_running_does_not_fail_the_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from botocore.exceptions import ClientError

    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")

    class ConflictError(ClientError):
        pass

    class FakeAgent:
        class exceptions:  # noqa: N801 - boto3 shape
            ConflictException = ConflictError

        def start_ingestion_job(self, **_request: Any) -> dict[str, Any]:
            raise ConflictError({"Error": {"Code": "ConflictException"}}, "StartIngestionJob")

    with mock_aws():
        session = boto3.Session(region_name="eu-west-1")
        account = session.client("sts").get_caller_identity()["Account"]
        session.client("s3").create_bucket(
            Bucket=f"suppliagent-dev-catalog-assets-{account}",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        for name in ("productSheetsKbId", "productSheetsDataSourceId"):
            session.client("ssm").put_parameter(
                Name=f"/suppliagent/dev/{name}", Value="X", Type="String"
            )
        real_client: Any = session.client
        monkeypatch.setattr(
            session,
            "client",
            lambda name, **kw: FakeAgent() if name == "bedrock-agent" else real_client(name, **kw),
        )
        assert seed.upload_sheets(session, "dev").startswith("already running")
