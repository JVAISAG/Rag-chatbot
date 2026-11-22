class ModelUnavailableError(RuntimeError):
    """The local model did not return a usable response."""


class DocumentError(ValueError):
    """A document cannot be safely read or indexed."""


class WebSearchUnavailableError(RuntimeError):
    """The configured search service could not return results."""
