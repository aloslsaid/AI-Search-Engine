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
4. Provide Telegram and provider credentials only through environment variables or an untracked local `.env` file. Never paste secrets into source code or commit them.
5. Inspect `bot.py` for the intended entry point, then run the documented command from the repository root. The root file list does not include an `.env.example`, so required variable names should be verified in the configuration source before use.

The `run.bat` and `setup.bat` files are Windows-specific helpers; review them before execution. Do not run setup scripts with elevated privileges unless you understand every command.

## Data and testing

The bot may create or update a local SQLite database. Back it up before changing database code and avoid committing user conversations. No test files were visible at the repository root, so a working test command is not currently documented. Add tests for configuration validation, search-provider failures, message limits, and database isolation before production use.

## Deployment notes

Use a dedicated bot account, least-privilege credentials, provider rate limits, secure logs that omit tokens and private conversations, and a process manager appropriate to your host. This project is not a substitute for provider terms or content-safety controls.
