class LLMShellError(Exception):
    """Base exception for LLM Shell."""


class ConflictError(LLMShellError):
    """409 - conflict state error."""


class NotFoundError(LLMShellError):
    """404 - resource not found."""


class BadRequestError(LLMShellError):
    """400 - invalid request error."""


class InternalError(LLMShellError):
    """500 - internal server error."""
