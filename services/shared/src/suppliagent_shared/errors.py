"""Typed errors. Tools return `{"error": code}` to the agent, never the message."""


class SuppliAgentError(Exception):
    code = "INTERNAL_ERROR"


class InvalidInputError(SuppliAgentError):
    code = "INVALID_INPUT"


class NotFoundError(SuppliAgentError):
    code = "NOT_FOUND"


class AccessDeniedError(SuppliAgentError):
    code = "ACCESS_DENIED"


class ChannelUnavailableError(SuppliAgentError):
    """The message cannot go out on this channel now (e.g. WhatsApp window closed, E-09)."""

    code = "CHANNEL_UNAVAILABLE"
