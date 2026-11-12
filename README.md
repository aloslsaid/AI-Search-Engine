# INFINITRIX SEARCH

INFINITRIX SEARCH is an asynchronous Telegram assistant built with Python, aiogram and aiohttp. It combines OpenRouter-powered chat with optional SerpApi web, image, video, news and reverse-image search.

## Features

- Telegram bot commands and conversational history.
- OpenRouter chat with configurable model and prompt.
- Optional web, image, video, news and reverse-image search.
- SQLite-backed conversation and usage data.
- Per-user anti-spam controls, usage limits and bounded conversation history.
- Configurable image upload host for reverse-image search.

## Requirements

- Python 3.10+
- Telegram bot token
- OpenRouter API key
- Optional SerpApi key for search commands

## Setup

From the repository root:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, and your numeric Telegram `OWNER_ID`. Keep the real `.env` file private and untracked.

```bash
# Windows
Copy-Item .env.example .env
# macOS/Linux
cp .env.example .env

python bot.py
```

Search features remain disabled until `SERPAPI_API_KEY` is configured. The bot can still provide AI chat without it.

## Configuration

See `.env.example` for model, token, timeout, history, anti-spam, usage-limit and search settings. Invalid numeric settings are rejected at startup. The SQLite database and rotating logs are created under the configured local paths.

## Security and privacy

- Use a dedicated Telegram bot and keep provider credentials in environment variables.
- Never commit `.env`, SQLite databases, logs or user conversation data.
- Search results and uploaded image URLs are external, untrusted content.
- Reverse-image search uploads the selected image to a temporary third-party image host before querying SerpApi. Do not use this feature with confidential or sensitive images.
- Review provider quotas, terms, retention and privacy policies before enabling public use.
- Run with least privilege and monitor API costs and rate limits.

## Tests

No complete automated test suite is currently declared. Add tests for configuration validation, database isolation, anti-spam limits, provider failures, and safe message formatting before production deployment.

## License

No license is declared. All rights reserved unless the repository owner adds an explicit license.
