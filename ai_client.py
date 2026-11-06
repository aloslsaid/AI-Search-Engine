"""OpenRouter chat-completions client with validation, retries and safe errors."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger("infinitrix.ai")

API_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class AIError(Exception):
    """AI request failed.

    user_message: safe text to show any user.
    detail: technical detail (shown to the bot owner only, and logged).
    """

    def __init__(self, user_message: str, detail: str = "") -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.detail = detail
        self.retryable = False


def _extract_error(data: Any) -> tuple[str, Any]:
    """Return (message, code) from an OpenRouter error body."""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err), err.get("code")
        if err:
            return str(err), None
    return "", None


def _status_to_error(status: int, detail: str) -> AIError:
    if status in (401, 403):
        return AIError(
            "⚠️ الخدمة غير متاحة حالياً بسبب مشكلة في إعدادات الحساب. أبلغ مالك البوت.",
            f"HTTP {status}: {detail}",
        )
    if status == 402:
        return AIError(
            "⚠️ رصيد الذكاء الاصطناعي نفد. أبلغ مالك البوت.",
            f"HTTP 402 (no credits): {detail}",
        )
    if status in (400, 404, 422):
        return AIError(
            "⚠️ تعذّر معالجة الطلب أو أن النموذج غير متاح حالياً. جرّب /clear ثم أعد المحاولة.",
            f"HTTP {status}: {detail}",
        )
    if status == 429:
        return AIError("⏳ الضغط مرتفع على النموذج الآن. حاول بعد لحظات.", f"HTTP 429: {detail}")
    if status >= 500 or status == 408:
        return AIError("⚠️ خطأ مؤقت في خدمة الذكاء الاصطناعي. حاول مرة أخرى بعد قليل.", f"HTTP {status}: {detail}")
    return AIError("⚠️ حدث خطأ غير متوقع في خدمة الذكاء الاصطناعي.", f"HTTP {status}: {detail}")


class OpenRouterClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
        timeout: float = 120,
        app_name: str = "INFINITRIX SEARCH",
        app_url: str = "",
        max_attempts: int = 3,
    ) -> None:
        self.session = session
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.app_name = app_name
        self.app_url = app_url
        self.max_attempts = max(1, max_attempts)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.app_name,
        }
        if self.app_url:
            headers["HTTP-Referer"] = self.app_url
        return headers

    async def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        last_error: AIError | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self._once(payload)
            except AIError as exc:
                last_error = exc
                retryable = getattr(exc, "retryable", False)
                if not retryable or attempt >= self.max_attempts:
                    raise
                delay = min(1.5 * attempt, 5.0)
                log.warning("OpenRouter attempt %s/%s failed (%s); retrying in %.1fs",
                            attempt, self.max_attempts, exc.detail, delay)
                await asyncio.sleep(delay)

        assert last_error is not None  # pragma: no cover
        raise last_error

    async def _once(self, payload: dict[str, Any]) -> str:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with self.session.post(
                API_URL, json=payload, headers=self._headers(), timeout=timeout
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None
                    body_text = ""
                    try:
                        body_text = (await resp.text())[:300]
                    except Exception:
                        pass
                else:
                    body_text = ""
        except asyncio.TimeoutError:
            err = AIError("⏳ انتهت مهلة الاتصال بالذكاء الاصطناعي. حاول مرة أخرى.", "timeout")
            err.retryable = True  # type: ignore[attr-defined]
            raise err from None
        except aiohttp.ClientError as exc:
            err = AIError("⚠️ تعذّر الاتصال بخدمة الذكاء الاصطناعي. تحقق من الإنترنت وحاول مجدداً.",
                          f"network error: {exc!r}")
            err.retryable = True  # type: ignore[attr-defined]
            raise err from None

        err_msg, err_code = _extract_error(data)

        if status != 200:
            detail = err_msg or body_text or "no body"
            error = _status_to_error(status, detail)
            error.retryable = status in RETRY_STATUS  # type: ignore[attr-defined]
            raise error

        # OpenRouter can return HTTP 200 with an "error" object in the body.
        if err_msg and not (isinstance(data, dict) and data.get("choices")):
            code = err_code if isinstance(err_code, int) else 500
            error = _status_to_error(code, err_msg)
            error.retryable = code in RETRY_STATUS  # type: ignore[attr-defined]
            raise error

        return self._parse_content(data)

    @staticmethod
    def _parse_content(data: Any) -> str:
        if not isinstance(data, dict):
            raise AIError("⚠️ رد غير صالح من الذكاء الاصطناعي. أعد المحاولة.", f"non-dict body: {type(data)}")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIError("⚠️ لم يُرجع النموذج أي رد. أعد المحاولة.", "no choices in response")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None

        if isinstance(content, list):  # some providers return content parts
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            finish = first.get("finish_reason") if isinstance(first, dict) else None
            raise AIError("⚠️ النموذج أرجع ردًا فارغًا. أعد صياغة سؤالك أو حاول ثانية.",
                          f"empty content, finish_reason={finish}")
        return content.strip()
