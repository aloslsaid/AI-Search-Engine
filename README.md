# INFINITRIX SEARCH 🤖🔎

An intelligent Telegram bot built with **Python + aiogram 3**, powered by the `cognitivecomputations/dolphin-mistral-24b-venice-edition` model through **OpenRouter**.

It features real-time internet search via **SerpApi**, including web, image, video, news, and reverse image search, alongside independent per-user conversation memory powered by **SQLite**.

It also allows the owner to customize the **System Prompt** directly through Telegram.

Designed for broad, unrestricted content discovery, including adult and graphic content, subject to the capabilities and policies of the connected providers.

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Getting API Keys](#getting-api-keys)
4. [Installation on Windows with VS Code](#installation-on-windows-with-vs-code)
5. [Configuring the `.env` File](#configuring-the-env-file)
6. [Running the Bot](#running-the-bot)
7. [Commands](#commands)
8. [System Prompt Management](#system-prompt-management)
9. [Usage Limits and Anti-Spam Protection](#usage-limits-and-anti-spam-protection)
10. [Reverse Image Search](#reverse-image-search)
11. [Project Structure](#project-structure)
12. [Testing](#testing)
13. [Troubleshooting](#troubleshooting)
14. [Security](#security)
15. [Running on Linux / Server](#running-on-linux--server)

---

## Features

- 💬 **AI-powered conversations** with independent per-user memory using SQLite, preserved across bot restarts.
- 🔎 **SerpApi integration** supporting multiple search engines:
  - Web Search (`google`)
  - Image Search (`google_images`)
  - Video Search (`google_videos`)
  - News Search (`google_news`)
  - Reverse Image Search (`google_reverse_image`) with `google_lens` as a fallback.
- 🧠 **Intelligent Search:** `/ask` and `/autosearch` allow the bot to search the internet first, then provide the retrieved results to the AI model to generate up-to-date answers with relevant links.
- 👑 **Owner-only System Prompt management:** `/setprompt`, `/showprompt`, and `/resetprompt` allow the bot owner to customize the system prompt directly through Telegram (`OWNER_ID`).
- 💾 **Persistent Custom System Prompt:** The customized prompt is stored in SQLite and automatically applied to every OpenRouter request.
- 🎯 **Default AI Personality:** Direct, capable, creative, and designed to minimize unnecessary refusals. The system prompt can be fully customized.
- 🌐 **Broad Content Discovery:** Supports searches across a wide range of topics and media, including adult and graphic content, depending on search-provider availability and applicable provider policies.
- 📊 **Configurable Daily Limits:** Adjustable daily quotas for AI messages and search operations, with anti-spam protection, cooldown intervals, flood detection, and temporary restrictions.
- 🛡 **Comprehensive Error Handling:** Handles invalid API keys, insufficient credits, service overload, timeouts, empty responses, and internet connectivity issues, with automatic retries to keep the bot running.
- ✂️ **Automatic Message Splitting:** Long responses are automatically divided to comply with Telegram's 4,096-character message limit.
- 🪟 **Windows and VS Code Support:** Includes convenient `setup.bat`, `run.bat`, and `.vscode` configuration files for easy setup and execution.
