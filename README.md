# INFINITRIX SEARCH — AI + Live Search for Telegram

> A Telegram AI assistant powered by Dolphin Mistral 24B Venice Edition through OpenRouter, with SerpAPI integration for web, image, video, news, and reverse-image search.

## Vision
INFINITRIX SEARCH combines conversational AI with live search in a Telegram bot. Users can ask questions in natural language, explore topics, and retrieve current web or media results without leaving Telegram.

The configured default model is **`cognitivecomputations/dolphin-mistral-24b-venice-edition`**. It is selected for a more direct and flexible conversational style. **SerpAPI** provides retrieved search results, allowing answers to incorporate current external information instead of depending only on the model's training data.

## Search modes
- **Web:** organic search results, answer boxes, and knowledge-graph summaries.
- **Images:** image results, thumbnails, and source links.
- **Videos:** video-focused results and available metadata.
- **News:** news result retrieval.
- **Reverse image:** search based on an image input.

Search responses are normalized into structured results with titles, URLs, snippets, source labels, thumbnails, dates, and durations where available.

## AI assistant features
- OpenRouter chat-completions integration.
- Configurable model, temperature, token limit, and request timeout.
- Per-user conversation history with configurable limits.
- Retry handling for temporary provider errors and rate limits.
- Clear user-facing errors separated from technical diagnostics.
- Configurable system prompt and language-aware responses.

## Architecture
- `bot.py` — Telegram bot entry point and application lifecycle.
- `ai_client.py` — asynchronous OpenRouter client.
- `search.py` — SerpAPI client and result parsers.
- `handlers.py` — Telegram command and message handlers.
- `core.py` — shared application context.
- `database.py` — SQLite persistence.
- `utils.py` — anti-spam and shared utilities.
- `config.py` — environment configuration.
- `test_core.py` — core behavior tests.

Built with Python, aiogram 3, aiohttp, SQLite, OpenRouter, SerpAPI, and python-dotenv.

## Conversational style and boundaries
The default prompt is designed to avoid unnecessary moralizing and to handle a broad range of sensitive, controversial, fictional, and adult topics in a direct tone. This is not a promise to bypass provider safeguards, Telegram rules, or applicable laws. Model behavior may vary by provider and model revision; retrieved web pages can also be inaccurate or malicious, so results must be evaluated rather than blindly trusted.

## Requirements
- Python 3.10+
- Telegram bot token from BotFather.
- OpenRouter API key with access to the selected Dolphin model.
- SerpAPI key for live search.

## Configuration
Create `.env` in the project root:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
OPENROUTER_API_KEY=your_openrouter_api_key
SERPAPI_API_KEY=your_serpapi_key
OWNER_ID=your_numeric_telegram_user_id
OPENROUTER_MODEL=cognitivecomputations/dolphin-mistral-24b-venice-edition
TEMPERATURE=0.8
MAX_OUTPUT_TOKENS=2048
SEARCH_RESULTS_COUNT=8
IMAGE_HOST=litterbox
```
Additional options cover database location, logging, daily usage limits, anti-spam timing, conversation history, request limits, and search language/region. Keep all secrets in the untracked `.env` file.

## Install and run
```bash
git clone https://github.com/aloslsaid/AI-Search-Engine.git
cd AI-Search-Engine
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python bot.py
```
On Windows, `setup.bat` is also provided as a setup helper. The application entry point is `bot.py`.

## Runtime notes
- OpenRouter credentials and model availability affect AI replies.
- SerpAPI credentials and quotas affect search.
- SQLite and rotating log files are runtime data; inspect them before publishing.
- The repository currently contains SQLite database and WAL/SHM files. Remove or reset personal runtime records before distributing a public copy.

## Skills demonstrated
Telegram automation · LLM integration · Live web retrieval · Media search · Async Python · API reliability · SQLite · Conversation memory · Rate limiting
