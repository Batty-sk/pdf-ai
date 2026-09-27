"""OpenAI-compatible chat completions.

The base URL is configurable, so the same client talks to OpenAI, LM Studio,
Ollama, and other servers that implement this API. Keys are read from
settings at call time and are not written to logs.
"""

from __future__ import annotations

import logging
import time

from utils.config import SettingsStore
from utils.errors import ApiError, InvalidApiKeyError, NetworkError, RateLimitError
from utils.security import get_api_key

logger = logging.getLogger(__name__)

# Used only when the selected Gemini model answers HTTP 503 (capacity).
_GEMINI_FALLBACKS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash")


class OpenAICompatibleProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ):
        if not api_key.strip():
            raise InvalidApiKeyError("Add an API key in Settings before asking a question.")
        if not base_url.startswith(("http://", "https://")):
            raise ApiError("The API endpoint must start with http:// or https://.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._use_completion_tokens = False

    @classmethod
    def from_settings(cls, settings: SettingsStore, data_dir) -> "OpenAICompatibleProvider":
        return cls(
            api_key=get_api_key(data_dir),
            base_url=settings.base_url,
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )

    def complete(self, messages: list[dict], *, json_mode: bool = True) -> str:
        logger.info("LLM request model=%s json_mode=%s", self.model, json_mode)
        use_json = json_mode
        try:
            return self._call_resilient(messages, json_mode=use_json)
        except Exception as exc:
            if use_json and _json_mode_rejected(exc):
                logger.info("Endpoint rejected JSON mode; retrying without it")
                use_json = False
                try:
                    return self._call_resilient(messages, json_mode=False)
                except Exception as retry_exc:
                    exc = retry_exc
            if _token_param_rejected(exc) and not self._use_completion_tokens:
                self._use_completion_tokens = True
                try:
                    return self._call_resilient(messages, json_mode=use_json)
                except Exception as retry_exc:
                    exc = retry_exc
            if _transient(exc) and _is_gemini(self.base_url):
                return self._try_fallbacks(messages, json_mode=use_json)
            raise _map_error(exc) from None

    def _call_resilient(self, messages: list[dict], *, json_mode: bool) -> str:
        """Retry capacity errors. Gemini often returns 503 while a model is busy."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                return self._call(messages, json_mode=json_mode)
            except Exception as exc:
                last = exc
                if not _transient(exc) or attempt == 2:
                    raise
                logger.info("AI service busy (attempt %s); retrying", attempt + 1)
                time.sleep(0.8 * (attempt + 1))
        assert last is not None
        raise last

    def _try_fallbacks(self, messages: list[dict], *, json_mode: bool) -> str:
        original = self.model
        last: Exception | None = None
        for model in _GEMINI_FALLBACKS:
            if model == original:
                continue
            self.model = model
            logger.info("Selected model is busy; trying %s", model)
            try:
                return self._call(messages, json_mode=json_mode)
            except Exception as exc:
                last = exc
                if not _transient(exc):
                    break
        self.model = original
        raise _map_error(last or ApiError("The AI service is busy. Wait a moment and try again.")) from None

    def _call(self, messages: list[dict], *, json_mode: bool) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60.0, max_retries=0)
        token_key = "max_completion_tokens" if self._use_completion_tokens else "max_tokens"
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            token_key: self.max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        if not response.choices:
            raise ApiError("The AI service returned an empty response.")
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise ApiError("The AI service returned an empty response.")
        return content


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__} {exc}".lower()


def _json_mode_rejected(exc: Exception) -> bool:
    text = _error_text(exc)
    return "response_format" in text or "json_object" in text or "json mode" in text


def _token_param_rejected(exc: Exception) -> bool:
    text = _error_text(exc)
    return "max_tokens" in text and ("unsupported" in text or "not supported" in text or "invalid" in text)


def _is_gemini(base_url: str) -> bool:
    return "generativelanguage.googleapis.com" in base_url


def _transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {500, 502, 503, 504}:
        return True
    text = _error_text(exc)
    return "unavailable" in text or "high demand" in text


def _map_error(exc: Exception) -> Exception:
    """Turn provider exceptions into short messages that do not echo the request."""
    if isinstance(exc, (InvalidApiKeyError, RateLimitError, NetworkError, ApiError)):
        return exc
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError as OpenAIRateLimitError,
        )
    except Exception:
        return ApiError("The AI service could not complete the request.")

    if isinstance(exc, AuthenticationError):
        return InvalidApiKeyError("The API key was rejected. Check it in Settings.")
    if isinstance(exc, OpenAIRateLimitError):
        return RateLimitError("The AI service is rate limiting requests. Wait a moment and try again.")
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return NetworkError("Could not reach the AI service. Check the endpoint and your connection.")

    status = getattr(exc, "status_code", None)
    if status == 401:
        return InvalidApiKeyError("The API key was rejected. Check it in Settings.")
    if status == 429:
        return RateLimitError("The AI service is rate limiting requests. Wait a moment and try again.")
    if status == 404:
        return ApiError("The model name was not accepted by the API. Check Settings.")
    if status in {500, 502, 503, 504}:
        return ApiError("The AI service is busy right now. Wait a moment and try again.")
    if status is not None:
        return ApiError(f"The AI service returned an error (HTTP {status}). Check the model name and endpoint.")
    return ApiError("The AI service could not complete the request.")
