"""Errors the interface can show without exposing internals."""


class AppError(Exception):
    """Base for expected failures."""


class PdfError(AppError):
    """A PDF could not be used."""


class InvalidPdfError(PdfError):
    """The file is not a readable PDF."""


class PasswordProtectedError(PdfError):
    """The PDF needs a password."""


class ScannedPdfError(PdfError):
    """The PDF has no text layer and OCR is unavailable."""


class EmptyPdfError(PdfError):
    """The PDF has no pages or no readable text."""


class UnsupportedFileError(PdfError):
    """The file is not a PDF."""


class FileTooLargeError(PdfError):
    """The file exceeds the local size limit."""


class LlmError(AppError):
    """The language-model request failed in a way the user can act on."""


class InvalidApiKeyError(LlmError):
    """The API key was missing or rejected."""


class RateLimitError(LlmError):
    """The provider asked us to slow down."""


class NetworkError(LlmError):
    """The endpoint could not be reached."""


class ApiError(LlmError):
    """The provider returned an error response."""
