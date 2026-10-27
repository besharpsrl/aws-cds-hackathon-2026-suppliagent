"""match_products and search_catalog (FN-07, F-05, TECHNICAL_FLOWS §6.5): raw order line to catalog
SKUs. The score blends semantic similarity (S3 Vectors), lexical similarity (name, synonyms,
abbreviation prefixes) and the customer's order history; the agent decides what to ask.

Environment: `TABLE_PREFIX`, `VECTOR_BUCKET_NAME`, `INDEX_NAME`, `EVENT_BUS_NAME`,
`MATCH_AUTO_THRESHOLD`, `MATCH_ASK_THRESHOLD`.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import json
import os
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from functools import cache
from typing import Any, Literal

import boto3
from aws_lambda_powertools import Logger
from pydantic import BaseModel, ConfigDict, Field
from suppliagent_shared.auth import CallerContext, caller_scope
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import AccessDeniedError
from suppliagent_shared.models import Role

logger = Logger(service="tool-catalog")
SOURCE = "suppliagent.tool-catalog"

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"  # same model as the catalog indexer (T-06)
DIMENSIONS = 1024
POOL = 10  # semantic candidates per query
MAX_CANDIDATES = 3  # F-05: at most 3 options + "Other"
HISTORY_ORDERS = 20
# ponytail: weights and the cosine rescale are first guesses; calibrate with the FN-07 eval.
SEMANTIC_WEIGHT = 0.5
SIM_FLOOR, SIM_SPAN = 0.3, 0.6  # Titan cosine similarity of unrelated text ~0.3, a hit ~0.9
HISTORY_BONUS = 0.10  # + up to the same again by how often it was ordered
USUAL_BONUS = 0.25  # "il solito X": + up to 0.15 by how often it was ordered
UNIT_PENALTY = 0.10
TIE_MARGIN = 0.05  # two near-equal leaders must not auto-match
USUAL = re.compile(r"^(il|lo|la|i|gli|le)\s+solit[oaie]\s+(di\s+|del\s+|della\s+)?", re.IGNORECASE)
UNITS = {
    "ct": "ct", "cs": "ct", "cartone": "ct", "cartoni": "ct", "cassa": "ct", "casse": "ct",
    "pz": "pz", "pezzo": "pz", "pezzi": "pz", "conf": "pz", "confezione": "pz", "confezioni": "pz",
    "kg": "kg", "chili": "kg", "chilo": "kg", "chilogrammi": "kg",
    "lt": "lt", "l": "lt", "litro": "lt", "litri": "lt",
}  # fmt: skip


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller: CallerContext  # set by the agent code, never by the model


class MatchProductsInput(ToolInput):
    rawText: str = Field(min_length=1, max_length=300)
    customerId: str = Field(max_length=64)
    rawUnit: str | None = Field(None, max_length=30)


class SearchCatalogInput(ToolInput):
    query: str = Field(min_length=1, max_length=300)
    category: str | None = Field(None, max_length=100)


@cache
def _bedrock() -> Any:
    return boto3.client("bedrock-runtime")


@cache
def _vectors() -> Any:
    return boto3.client("s3vectors")


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def _lexical(raw: str, names: list[str]) -> float:
    """Best of: whole-string similarity, share of raw tokens that start a name token ("mozz")."""
    tokens = [t for t in raw.split() if len(t) >= 2]
    best = 0.0
    for name in map(_norm, names):
        if not name:
            continue
        name_tokens = name.split()
        prefix = (
            sum(any(n.startswith(t) for n in name_tokens) for t in tokens) / len(tokens)
            if tokens
            else 0.0
        )
        best = max(best, SequenceMatcher(None, raw, name).ratio(), prefix)
    return best


def _query(text: str, top_k: int, category: str | None = None) -> list[dict[str, Any]]:
    response = _bedrock().invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True}),
    )
    embedding = json.loads(response["body"].read())["embedding"]
    extra = {"filter": {"category": category}} if category else {}
    hits: list[dict[str, Any]] = _vectors().query_vectors(
        vectorBucketName=os.environ["VECTOR_BUCKET_NAME"],
        indexName=os.environ["INDEX_NAME"],
        queryVector={"float32": embedding},
        topK=top_k,
        returnDistance=True,
        **extra,
    )["vectors"]
    return hits


def _similarity(hit: dict[str, Any]) -> float:
    """Cosine distance to a 0-1 similarity score."""
    return min(1.0, max(0.0, (1 - float(hit["distance"]) - SIM_FLOOR) / SIM_SPAN))


def _require_customer_access(caller: CallerContext, customer_id: str | None = None) -> None:
    if caller.role is Role.UNKNOWN or not caller.contactId:
        raise AccessDeniedError  # F-02: identify first
    allowed = caller_scope(caller).customer_ids
    if not allowed or (customer_id is not None and customer_id not in allowed):
        raise AccessDeniedError


def _history(customer_id: str) -> tuple[Counter[str], dict[str, str]]:
    """How many of the last orders held each SKU, and the descriptions used there."""
    orders = table("order-history").query(
        KeyConditionExpression="customerId = :c",
        ExpressionAttributeValues={":c": customer_id},
        ScanIndexForward=False,
        Limit=HISTORY_ORDERS,
    )["Items"]
    counts: Counter[str] = Counter()
    descriptions: dict[str, str] = {}
    for order in orders:
        for sku in {line["sku"] for line in order["lines"]}:
            counts[sku] += 1
        for line in order["lines"]:
            descriptions[line["sku"]] = line.get("description", "")
    return counts, descriptions


def _unit(value: str | None) -> str | None:
    return UNITS.get(_norm(value)) if value else None


def _candidate(
    product: dict[str, Any],
    *,
    similarity: float,
    raw: str,
    unit: str | None,
    counts: Counter[str],
    usual: bool,
) -> dict[str, Any]:
    names = [product["name"], *(product.get("synonyms") or [])]
    score = SEMANTIC_WEIGHT * similarity + (1 - SEMANTIC_WEIGHT) * _lexical(raw, names)
    ordered = counts[product["sku"]]
    if ordered:
        share = ordered / max(counts.values())
        score += (USUAL_BONUS + 0.15 * share) if usual else (HISTORY_BONUS * (1 + share))
    product_unit = _unit(product.get("unit"))
    if unit and product_unit and unit != product_unit:
        score -= UNIT_PENALTY
    return {
        "sku": product["sku"],
        "name": product["name"],
        "brand": product.get("brand"),
        "format": product.get("format"),
        "unit": product.get("unit"),
        "confidence": score,  # unclamped while ranking: bonuses must not erase the margin
        "purchasedBefore": bool(ordered),
        "timesOrdered": ordered,
        "discontinued": not product.get("active", True),
    }


def match_products(args: MatchProductsInput) -> dict[str, Any]:
    _require_customer_access(args.caller, args.customerId)
    auto = float(os.environ["MATCH_AUTO_THRESHOLD"])
    ask = float(os.environ["MATCH_ASK_THRESHOLD"])
    text = args.rawText.strip()
    usual = bool(USUAL.match(text))
    raw = _norm(USUAL.sub("", text, count=1))
    unit = _unit(args.rawUnit)
    counts, descriptions = _history(args.customerId)

    similarity = {hit["key"]: _similarity(hit) for hit in _query(raw, POOL)}
    # ordered products the vectors missed (abbreviations): found by their description
    for sku, description in descriptions.items():
        if sku not in similarity and _lexical(raw, [description]) >= ask:
            similarity[sku] = 0.0
    products = table("products")
    candidates = []
    for sku, sim in similarity.items():
        product = products.get_item(Key={"sku": sku}).get("Item")
        if product:
            candidates.append(
                _candidate(product, similarity=sim, raw=raw, unit=unit, counts=counts, usual=usual)
            )
    candidates.sort(key=lambda c: (-c["confidence"], -c["timesOrdered"]))
    top = candidates[:MAX_CANDIDATES]

    if top:
        # Never auto-match when the answer is not clear: near-tie, discontinued, or a "usual"
        # that the history cannot settle (nothing ordered, or two products ordered as often).
        lead = top[0]
        tie = len(top) > 1 and lead["confidence"] - top[1]["confidence"] < TIE_MARGIN
        usual_unclear = usual and (
            not lead["purchasedBefore"]
            or (len(top) > 1 and top[1]["timesOrdered"] >= 0.8 * lead["timesOrdered"])
        )
        if tie or usual_unclear or lead["discontinued"]:
            lead["confidence"] = min(lead["confidence"], auto - 0.01)
    stock = table("stock")
    for c in top:
        c["confidence"] = round(min(1.0, max(0.0, c["confidence"])), 2)
        if c["discontinued"]:  # C6: the official substitute
            c["substitutes"] = (
                stock.get_item(Key={"sku": c["sku"]}).get("Item", {}).get("substitutes", [])
            )
    confidence = top[0]["confidence"] if top else 0.0
    status = "MATCHED" if confidence >= auto else "AMBIGUOUS" if confidence >= ask else "UNMATCHED"
    _emit(args.caller, status, confidence)
    return {"status": status, "usual": usual, "candidates": top}


def _emit(caller: CallerContext, status: str, confidence: float) -> None:
    """`order.line_matched` (02 §6.4); IDs and numbers only, never the line text."""
    try:
        put_event(
            SOURCE,
            "order.line_matched",
            {"conversationId": caller.conversationId, "status": status, "confidence": confidence},
        )
    except Exception:
        logger.warning("event not sent")  # quality metric only: never fail the match for it


def search_catalog(args: SearchCatalogInput) -> dict[str, Any]:
    _require_customer_access(args.caller)
    results = []
    products = table("products")
    for hit in _query(_norm(args.query), MAX_CANDIDATES + 2, args.category):
        product = products.get_item(Key={"sku": hit["key"]}).get("Item")
        if product and product.get("active", True):
            results.append(
                {k: product.get(k) for k in ("sku", "name", "brand", "category", "format", "unit")}
            )
    status: Literal["OK", "NO_RESULTS"] = "OK" if results else "NO_RESULTS"
    return {"status": status, "results": results}
