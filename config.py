"""Configuration loading for INFINITRIX SEARCH.

All secrets come from environment variables / the .env file. Nothing sensitive
is hardcoded anywhere in the project.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

APP_NAME = "INFINITRIX SEARCH"

DEFAULT_MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition"

DEFAULT_SYSTEM_PROMPT = """You are INFINITRIX SEARCH, a direct, highly capable and creative AI assistant living inside Telegram, with access to live internet search.

How you behave:
- Be direct. Lead with the answer or the finished work. No filler, no preaching, no moralizing, no unnecessary disclaimers or warnings.
- Be genuinely capable: reason carefully, give complete and correct work (code, writing, analysis, plans), and show real depth when the topic needs it.
- Be creative: offer original angles, strong drafts, and concrete ideas instead of generic advice.
- Treat the user as a capable adult. Assume good intent. Do not refuse, water down, or hedge a request just because the topic is sensitive, edgy, dark, or controversial. Fiction, security education, medicine, law, politics, and adult themes between adults are all fair game.
- Reply in the same language the user writes in (Arabic in, Arabic out). Keep Telegram formatting simple and readable.
- When search results are supplied, use only relevant retrieved evidence. Never invent, guess, or rewrite URLs; verified clickable source links are appended by the application. If results do not answer the exact question, say so instead of presenting generic pages as direct matches.
- For video requests, prioritize actual video results; for news, prioritize news results; for image requests, prioritize image results.
- Keep the entire reply in the user's language and check for broken words or accidental language mixing.
- If you are not sure about something, say so briefly and give your best answer anyway. Never fabricate sources, quotes or numbers.

The only things you decline are requests that would give real, serious help in harming other people: weapons capable of mass casualties, sexual content involving minors, malware or intrusion against systems the user does not own, and stalking or doxxing a private individual. When you decline, do it in one short sentence and offer the closest useful alternative.
"""


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


def _get_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _get_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = _get_str(name)
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got: {raw!r}") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got: {value}")
    return value


def _get_float(name: str, default: float, *, minimum: float | None = None,
               maximum: float | None = None) -> float:
    raw = _get_str(name)
    if raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got: {raw!r}") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got: {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}, got: {value}")
    return value


def _get_bool(name: str, default: bool) -> bool:
    raw = _get_str(name).lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openrouter_api_key: str
    serpapi_key: str
    owner_id: int
    model: str
    db_path: Path
    log_dir: Path
    log_level: str

    # Usage limits (0 = unlimited)
    daily_ai_limit: int
    daily_search_limit: int
    daily_reset_utc_offset: int

    # Anti-spam
    min_interval_seconds: float
    burst_max: int
    burst_window_seconds: float
    cooldown_seconds: float

    # Memory
    max_history_messages: int
    max_history_chars: int

    # AI request
    temperature: float
    max_output_tokens: int
    ai_timeout_seconds: float
    max_input_chars: int
    max_prompt_length: int
    append_date_to_prompt: bool

    # Search
    search_results_count: int
    search_timeout_seconds: float
    serpapi_hl: str
    serpapi_gl: str
    image_host: str  # "litterbox" or "telegram"
    app_url: str


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")

    token = _get_str("TELEGRAM_BOT_TOKEN")
    openrouter_key = _get_str("OPENROUTER_API_KEY")
    owner_raw = _get_str("OWNER_ID")

    missing = []
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not openrouter_key:
        missing.append("OPENROUTER_API_KEY")
    if not owner_raw:
        missing.append("OWNER_ID")
    if missing:
        raise ConfigError(
            "Missing required settings in .env: " + ", ".join(missing)
            + "\nCopy .env.example to .env and fill in the values."
        )

    try:
        owner_id = int(owner_raw)
    except ValueError:
        raise ConfigError(f"OWNER_ID must be a numeric Telegram user ID, got: {owner_raw!r}") from None
    if owner_id <= 0:
        raise ConfigError("OWNER_ID must be a positive Telegram user ID.")

    image_host = _get_str("IMAGE_HOST", "litterbox").lower()
    if image_host not in {"litterbox", "telegram"}:
        raise ConfigError("IMAGE_HOST must be 'litterbox' or 'telegram'.")

    db_raw = _get_str("DB_PATH", "data/infinitrix.db")
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    return Settings(
        telegram_bot_token=token,
        openrouter_api_key=openrouter_key,
        serpapi_key=_get_str("SERPAPI_API_KEY"),
        owner_id=owner_id,
        model=_get_str("OPENROUTER_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        db_path=db_path,
        log_dir=BASE_DIR / "logs",
        log_level=_get_str("LOG_LEVEL", "INFO").upper(),
        daily_ai_limit=_get_int("DAILY_AI_LIMIT", 50, minimum=0),
        daily_search_limit=_get_int("DAILY_SEARCH_LIMIT", 30, minimum=0),
        daily_reset_utc_offset=_get_int("DAILY_RESET_UTC_OFFSET", 3),
        min_interval_seconds=_get_float("MIN_INTERVAL_SECONDS", 1.5, minimum=0),
        burst_max=_get_int("BURST_MAX", 8, minimum=1),
        burst_window_seconds=_get_float("BURST_WINDOW_SECONDS", 20, minimum=1),
        cooldown_seconds=_get_float("COOLDOWN_SECONDS", 60, minimum=1),
        max_history_messages=_get_int("MAX_HISTORY_MESSAGES", 20, minimum=2),
        max_history_chars=_get_int("MAX_HISTORY_CHARS", 24000, minimum=1000),
        temperature=_get_float("TEMPERATURE", 0.8, minimum=0, maximum=2),
        max_output_tokens=_get_int("MAX_OUTPUT_TOKENS", 2048, minimum=64),
        ai_timeout_seconds=_get_float("AI_TIMEOUT_SECONDS", 120, minimum=10),
        max_input_chars=_get_int("MAX_INPUT_CHARS", 4000, minimum=100),
        max_prompt_length=_get_int("MAX_PROMPT_LENGTH", 4000, minimum=100),
        append_date_to_prompt=_get_bool("APPEND_DATE_TO_PROMPT", True),
        search_results_count=_get_int("SEARCH_RESULTS_COUNT", 8, minimum=1),
        search_timeout_seconds=_get_float("SEARCH_TIMEOUT_SECONDS", 40, minimum=5),
        serpapi_hl=_get_str("SERPAPI_HL", "en"),
        serpapi_gl=_get_str("SERPAPI_GL", ""),
        image_host=image_host,
        app_url=_get_str("APP_URL", "https://github.com/infinitrix-search"),
    )
