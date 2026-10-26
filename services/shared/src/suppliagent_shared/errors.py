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
