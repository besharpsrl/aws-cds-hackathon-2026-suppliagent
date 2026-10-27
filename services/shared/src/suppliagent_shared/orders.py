"""Order status machine (02 §2.3) and line statuses (02 §2.4), shared by the orders tool and the
sweeper that expires drafts. Statuses are plain strings: they are what DynamoDB stores."""

from suppliagent_shared.errors import InvalidInputError

TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"NEEDS_CLARIFICATION", "PENDING_CONFIRMATION", "CANCELLED"}),
    "NEEDS_CLARIFICATION": frozenset({"DRAFT", "CANCELLED"}),
    "PENDING_CONFIRMATION": frozenset({"DRAFT", "CONFIRMED", "EXPIRED", "CANCELLED"}),
    "CONFIRMED": frozenset({"SUBMITTED", "CANCELLED"}),
    "SUBMITTED": frozenset({"SCHEDULED", "CANCELLED"}),
    "SCHEDULED": frozenset({"OUT_FOR_DELIVERY"}),
    "OUT_FOR_DELIVERY": frozenset({"DELIVERED", "DELIVERY_ISSUE"}),
    "DELIVERY_ISSUE": frozenset({"DELIVERED"}),
    # a problem is often noticed after the driver left (F-12): same issue flow
    "DELIVERED": frozenset({"DELIVERY_ISSUE"}),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset(),
}
EDITABLE = frozenset({"DRAFT", "NEEDS_CLARIFICATION", "PENDING_CONFIRMATION"})
AFTER_CONFIRMATION = frozenset({"CONFIRMED", "SUBMITTED"})  # changeable until the cut-off (F-08)
FREELY_CANCELLABLE = EDITABLE
UNRESOLVED_LINES = frozenset({"AMBIGUOUS", "UNMATCHED", "OUT_OF_STOCK"})
ACTIVE_LINES = frozenset({"MATCHED", "SUBSTITUTED", "ADJUSTED", "CONFIRMED"})


def check_transition(old: str, new: str) -> None:
    if new not in TRANSITIONS.get(old, frozenset()):
        raise InvalidInputError
