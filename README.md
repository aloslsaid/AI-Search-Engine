# INFINITRIX Search

INFINITRIX is a Python Telegram bot that combines conversational AI with web/media search integrations. The codebase includes bot and handler modules, a search module, an AI client, configuration and database modules, Windows helper scripts, and a `requirements.txt` manifest.

## Features described by the project

- Telegram conversations and per-user history stored with SQLite.
- Search through the configured SerpApi integration.
- AI responses through the configured OpenRouter model.
- Bot commands for search and conversation management, as implemented by the handlers.

Provider availability, quotas, and content policies apply. Search results should be treated as untrusted external content.

## Setup

1. Install Python and create a virtual environment.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Review `config.py` and the bot's configuration flow to identify required settings.
4. Copy `.env.example` to `.env` and set `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, and your numeric `OWNER_ID`. `SERPAPI_API_KEY` is optional; without it, search commands are disabled.
5. Keep `.env` private and untracked. Start the bot from the repository root with `python bot.py`.

The `run.bat` and `setup.bat` files are Windows-specific helpers; review them before execution. Do not run setup scripts with elevated privileges unless you understand every command.

## Data and testing

The bot may create or update a local SQLite database. Back it up before changing database code and avoid committing user conversations. No test files were visible at the repository root, so a working test command is not currently documented. Add tests for configuration validation, search-provider failures, message limits, and database isolation before production use.

## Deployment notes

Use a dedicated bot account, least-privilege credentials, provider rate limits, secure logs that omit tokens and private conversations, and a process manager appropriate to your host. This project is not a substitute for provider terms or content-safety controls.


## Reverse-image privacy

The reverse-image command temporarily uploads the selected image to an external public file host and then sends its URL to SerpApi. Do not use it for private, confidential, or biometric images unless you have permission and accept the third-party processing and retention terms. Ordinary web, image, video, and news search commands do not need this image upload.
