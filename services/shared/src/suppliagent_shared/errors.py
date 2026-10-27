"""Typed errors. Tools return `{"error": code}` to the agent, never the message."""


class SuppliAgentError(Exception):
    code = "INTERNAL_ERROR"


class InvalidInputError(SuppliAgentError):
    code = "INVALID_INPUT"


class NotFoundError(SuppliAgentError):
    code = "NOT_FOUND"


class AccessDeniedError(SuppliAgentError):
    code = "ACCESS_DENIED"


class UnsupportedMediaError(SuppliAgentError):
    code = "UNSUPPORTED_MEDIA"


class ExtractionFailedError(SuppliAgentError):
    code = "EXTRACTION_FAILED"


class ChannelUnavailableError(SuppliAgentError):
    """The message cannot go out on this channel now (e.g. WhatsApp window closed, E-09)."""

    code = "CHANNEL_UNAVAILABLE"


class ErpUnavailableError(SuppliAgentError):
    """The ERP did not answer (E-08): the order stays CONFIRMED and the caller retries."""

    code = "ERP_UNAVAILABLE"


class InvalidSkuError(SuppliAgentError):
    """The SKU is not in the catalog or no longer sold."""

    code = "INVALID_SKU"


class ConflictError(SuppliAgentError):
    """The order changed under the call (concurrent edit): nothing was written, try again."""

    code = "CONFLICT"


class OrderLockedError(SuppliAgentError):
    """Past the cut-off or already scheduled: handoff ORDER_LOCKED (F-08.C3)."""

    code = "ORDER_LOCKED"


class ConfirmationMismatchError(SuppliAgentError):
    """A confirmation button that does not answer the summary sent for this order."""

    code = "CONFIRMATION_MISMATCH"
