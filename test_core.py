from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _stubs  # noqa: F401  (sets up sys.path / aiohttp stub)
from tests._stubs import ClientError, FakeResponse, FakeSession

import ai_client
import config
import core
from ai_client import AIError, OpenRouterClient
from config import ConfigError, DEFAULT_SYSTEM_PROMPT, Settings
from core import AppContext, User, UserFacingError
from database import Database
from search import (
    SearchError,
    SearchItem,
    SearchResponse,
    SerpApiClient,
    build_ai_context,
    format_response_html,
    parse_news,
    parse_web,
    upload_temp_image,
)
from utils import AntiSpam, pack_blocks, split_message, today_key


def make_settings(tmp: Path, **overrides) -> Settings:
    base = dict(
        telegram_bot_token="t", openrouter_api_key="k", serpapi_key="s", owner_id=1,
        model="m", db_path=tmp / "t.db", log_dir=tmp / "logs", log_level="INFO",
        daily_ai_limit=3, daily_search_limit=2, daily_reset_utc_offset=3,
        min_interval_seconds=0.0, burst_max=100, burst_window_seconds=10, cooldown_seconds=60,
        max_history_messages=20, max_history_chars=24000, temperature=0.8,
        max_output_tokens=256, ai_timeout_seconds=10, max_input_chars=4000,
        max_prompt_length=500, append_date_to_prompt=True, search_results_count=5,
        search_timeout_seconds=10, serpapi_hl="en", serpapi_gl="", image_host="litterbox",
        app_url="",
    )
    base.update(overrides)
    return Settings(**base)


class FakeAI:
    def __init__(self, replies=None, error=None):
        self.replies = list(replies or ["ok"])
        self.error = error
        self.requests = []

    async def chat(self, messages):
        self.requests.append(messages)
        if self.error:
            raise self.error
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeSearch:
    enabled = True

    def __init__(self, resp=None, error=None):
        self.resp = resp
        self.error = error
        self.calls = []

    async def web(self, q):
        self.calls.append(("web", q))
        if self.error:
            raise self.error
        return self.resp

    async def images(self, q):
        self.calls.append(("images", q))
        if self.error:
            raise self.error
        return self.resp

    async def videos(self, q):
        self.calls.append(("videos", q))
        if self.error:
            raise self.error
        return self.resp

    async def news(self, q):
        self.calls.append(("news", q))
        if self.error:
            raise self.error
        return self.resp

    async def reverse_image(self, url):
        self.calls.append(("reverse", url))
        if self.error:
            raise self.error
        return self.resp


# ------------------------------------------------------------------ utils
class UtilsTests(unittest.TestCase):
    def test_split_short(self):
        self.assertEqual(split_message("hello"), ["hello"])
        self.assertEqual(split_message("   "), ["…"])

    def test_split_long_preserves_content_and_limit(self):
        text = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(60))
        parts = split_message(text, 1000)
        self.assertTrue(all(0 < len(p) <= 1000 for p in parts))
        self.assertEqual("".join(parts).replace("\n", "").replace(" ", ""),
                         text.replace("\n", "").replace(" ", ""))

    def test_split_no_whitespace_hard_cut(self):
        parts = split_message("x" * 10000, 4000)
        self.assertEqual([len(p) for p in parts], [4000, 4000, 2000])

    def test_split_arabic(self):
        text = "مرحبا بالعالم " * 1000
        parts = split_message(text)
        self.assertTrue(all(len(p) <= 4000 for p in parts))

    def test_pack_blocks(self):
        blocks = ["a" * 30, "b" * 30, "c" * 30]
        msgs = pack_blocks(blocks, limit=70)
        self.assertEqual(len(msgs), 2)
        self.assertTrue(all(len(m) <= 70 for m in msgs))
        self.assertEqual(pack_blocks(["z" * 200], limit=50)[0][-1], "…")

    def test_antispam(self):
        sp = AntiSpam(min_interval=1.0, burst_max=3, burst_window=10, cooldown=30)
        self.assertTrue(sp.check(1, now=100.0).allowed)
        v = sp.check(1, now=100.2)
        self.assertEqual((v.allowed, v.reason), (False, "too_fast"))
        self.assertTrue(sp.check(1, now=101.5).allowed)
        self.assertTrue(sp.check(1, now=103.0).allowed)
        v = sp.check(1, now=104.5)
        self.assertEqual((v.allowed, v.reason), (False, "blocked_now"))
        v = sp.check(1, now=110.0)
        self.assertEqual((v.allowed, v.reason), (False, "blocked"))
        self.assertTrue(sp.check(1, now=140.0).allowed)  # cooldown over
        self.assertTrue(sp.check(2, now=104.5).allowed)  # other users unaffected

    def test_today_key_offset(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 6, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(today_key(0, now), "2026-11-06")
        self.assertEqual(today_key(3, now), "2026-11-07")


# ----------------------------------------------------------------- config
class ConfigTests(unittest.TestCase):
    def test_missing_required(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(config, "load_dotenv", lambda *a, **k: None):
            with self.assertRaises(ConfigError) as cm:
                config.load_settings()
        self.assertIn("TELEGRAM_BOT_TOKEN", str(cm.exception))

    def test_valid_and_defaults(self):
        env = {"TELEGRAM_BOT_TOKEN": "tok", "OPENROUTER_API_KEY": "key", "OWNER_ID": "12345"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(config, "load_dotenv", lambda *a, **k: None):
            s = config.load_settings()
        self.assertEqual(s.owner_id, 12345)
        self.assertEqual(s.model, "cognitivecomputations/dolphin-mistral-24b-venice-edition")
        self.assertEqual(s.serpapi_key, "")

    def test_bad_owner_and_numbers(self):
        base = {"TELEGRAM_BOT_TOKEN": "tok", "OPENROUTER_API_KEY": "key"}
        for extra in ({"OWNER_ID": "abc"}, {"OWNER_ID": "5", "DAILY_AI_LIMIT": "x"},
                      {"OWNER_ID": "5", "IMAGE_HOST": "ftp"}, {"OWNER_ID": "-5"}):
            with mock.patch.dict(os.environ, {**base, **extra}, clear=True), \
                    mock.patch.object(config, "load_dotenv", lambda *a, **k: None):
                with self.assertRaises(ConfigError):
                    config.load_settings()


# --------------------------------------------------------------- database
class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "db.sqlite"
        self.db = Database(self.path)
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_memory_is_per_user_and_ordered(self):
        await self.db.add_exchange(1, "q1", "a1", keep=40)
        await self.db.add_exchange(2, "other", "other-a", keep=40)
        await self.db.add_exchange(1, "q2", "a2", keep=40)
        h1 = await self.db.get_history(1, 20, 10000)
        self.assertEqual([m["content"] for m in h1], ["q1", "a1", "q2", "a2"])
        h2 = await self.db.get_history(2, 20, 10000)
        self.assertEqual([m["content"] for m in h2], ["other", "other-a"])
        self.assertEqual(await self.db.clear_history(1), 4)
        self.assertEqual(await self.db.get_history(1, 20, 10000), [])
        self.assertEqual(len(await self.db.get_history(2, 20, 10000)), 2)

    async def test_history_limits_and_pruning(self):
        for i in range(30):
            await self.db.add_exchange(1, f"q{i}", f"a{i}", keep=10)
        self.assertEqual(await self.db.count_messages(1), 10)
        h = await self.db.get_history(1, 4, 10000)
        self.assertEqual([m["content"] for m in h], ["q28", "a28", "q29", "a29"])
        # char budget: only the newest pair fits
        h = await self.db.get_history(1, 20, 7)
        self.assertEqual(h[0]["role"], "user")

    async def test_history_starts_with_user(self):
        await self.db.add_exchange(1, "q1", "a1", keep=40)
        h = await self.db.get_history(1, 3, 10000)  # would start with assistant
        self.assertEqual(h[0]["role"], "user")

    async def test_prompt_persists_across_restart(self):
        await self.db.set_setting("system_prompt", "custom prompt ✓ عربي")
        await self.db.close()
        db2 = Database(self.path)
        await db2.init()
        self.assertEqual(await db2.get_setting("system_prompt"), "custom prompt ✓ عربي")
        self.assertTrue(await db2.delete_setting("system_prompt"))
        self.assertIsNone(await db2.get_setting("system_prompt"))
        self.assertFalse(await db2.delete_setting("system_prompt"))
        await db2.close()
        self.db = Database(self.path)  # for teardown
        await self.db.init()

    async def test_usage_limit_and_refund(self):
        day = "2026-11-06"
        self.assertEqual(await self.db.try_consume(1, day, "ai", 2), (True, 1))
        self.assertEqual(await self.db.try_consume(1, day, "ai", 2), (True, 2))
        self.assertEqual(await self.db.try_consume(1, day, "ai", 2), (False, 2))
        await self.db.refund(1, day, "ai")
        self.assertEqual(await self.db.try_consume(1, day, "ai", 2), (True, 2))
        self.assertEqual(await self.db.try_consume(2, day, "ai", 2), (True, 1))
        self.assertEqual(await self.db.try_consume(1, "2026-11-07", "ai", 2), (True, 1))
        self.assertEqual(await self.db.try_consume(1, day, "ai", 0), (True, 3))  # unlimited
        await self.db.refund(9, day, "ai")  # never goes negative
        self.assertEqual(await self.db.get_usage(9, day, "ai"), 0)

    async def test_concurrent_consume_is_atomic(self):
        results = await asyncio.gather(*[self.db.try_consume(1, "d", "ai", 5) for _ in range(20)])
        self.assertEqual(sum(1 for ok, _ in results if ok), 5)

    async def test_prefs_users_stats(self):
        await self.db.touch_user(1, "bob", "Bob")
        await self.db.touch_user(1, "bobby", "Bob B")
        await self.db.set_pref(1, "autosearch", "1")
        self.assertEqual(await self.db.get_pref(1, "autosearch"), "1")
        self.assertEqual(await self.db.get_pref(2, "autosearch", "0"), "0")
        stats = await self.db.stats(0)
        self.assertEqual(stats["users"], 1)


# -------------------------------------------------------------- AI client
class AIClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, session):
        return OpenRouterClient(session, "key", "model", timeout=5, app_url="http://x")

    @staticmethod
    def ok(text="hello"):
        return FakeResponse(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})

    async def test_success_and_payload(self):
        session = FakeSession(self.ok("  hi there  "))
        out = await self.client(session).chat([{"role": "user", "content": "x"}])
        self.assertEqual(out, "hi there")
        _, url, kwargs = session.calls[0]
        self.assertEqual(url, ai_client.API_URL)
        self.assertEqual(kwargs["json"]["model"], "model")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer key")

    async def test_auth_error_not_retried_and_not_leaky(self):
        session = FakeSession(FakeResponse(401, {"error": {"message": "No auth credentials"}}))
        with self.assertRaises(AIError) as cm:
            await self.client(session).chat([])
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("No auth", cm.exception.user_message)
        self.assertIn("No auth", cm.exception.detail)

    async def test_rate_limit_retries_then_succeeds(self):
        session = FakeSession(FakeResponse(429, {"error": {"message": "slow"}}), self.ok("fine"))
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            out = await self.client(session).chat([])
        self.assertEqual(out, "fine")
        self.assertEqual(len(session.calls), 2)

    async def test_server_error_gives_up_after_attempts(self):
        session = FakeSession(*[FakeResponse(503, {"error": "down"}) for _ in range(3)])
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            with self.assertRaises(AIError):
                await self.client(session).chat([])
        self.assertEqual(len(session.calls), 3)

    async def test_timeout_and_network_error(self):
        session = FakeSession(asyncio.TimeoutError(), ClientError("boom"), asyncio.TimeoutError())
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()):
            with self.assertRaises(AIError) as cm:
                await self.client(session).chat([])
        self.assertIn("مهلة", cm.exception.user_message)

    async def test_empty_and_malformed_responses(self):
        for resp in (
            FakeResponse(200, {"choices": []}),
            FakeResponse(200, {"choices": [{"message": {"content": "   "}}]}),
            FakeResponse(200, {"choices": [{"message": None}]}),
            FakeResponse(200, ["not", "a", "dict"]),
            FakeResponse(200, None, json_error=True),
        ):
            with self.assertRaises(AIError):
                await self.client(FakeSession(resp)).chat([])

    async def test_http_200_with_error_body(self):
        session = FakeSession(FakeResponse(200, {"error": {"message": "credits", "code": 402}}))
        with self.assertRaises(AIError) as cm:
            await self.client(session).chat([])
        self.assertIn("رصيد", cm.exception.user_message)

    async def test_content_parts_list(self):
        resp = FakeResponse(200, {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]})
        self.assertEqual(await self.client(FakeSession(resp)).chat([]), "ab")


# -------------------------------------------------------------- search
class SearchTests(unittest.IsolatedAsyncioTestCase):
    def client(self, session, key="sk"):
        return SerpApiClient(session, key, timeout=5, num_results=3)

    async def test_web_parsing_and_answer_box(self):
        data = {
            "answer_box": {"answer": "42"},
            "organic_results": [
                {"title": "A", "link": "https://a.com", "snippet": "sa", "displayed_link": "a.com"},
                {"title": "no link"},
                {"title": "B", "link": "https://b.com"},
                {"title": "C", "link": "https://c.com"},
                {"title": "D", "link": "https://d.com"},
            ],
        }
        session = FakeSession(FakeResponse(200, data))
        resp = await self.client(session).web("q")
        self.assertEqual(resp.answer, "42")
        self.assertEqual([i.url for i in resp.items], ["https://a.com", "https://b.com", "https://c.com"])
        params = session.calls[0][2]["params"]
        self.assertEqual(params["engine"], "google")
        self.assertEqual(params["api_key"], "sk")

    async def test_engines_used(self):
        for method, engine, arg in (("images", "google_images", "q"), ("videos", "google_videos", "q"),
                                    ("news", "google_news", "q")):
            session = FakeSession(FakeResponse(200, {}))
            await getattr(self.client(session), method)(arg)
            self.assertEqual(session.calls[0][2]["params"]["engine"], engine)

    async def test_images_videos_news_parsers(self):
        session = FakeSession(FakeResponse(200, {"images_results": [
            {"title": "pic", "link": "https://p.com", "original": "https://p.com/1.jpg",
             "thumbnail": "https://t.com/1.jpg", "source": "P"}]}))
        resp = await self.client(session).images("cats")
        self.assertEqual(resp.items[0].original, "https://p.com/1.jpg")

        session = FakeSession(FakeResponse(200, {"video_results": [
            {"title": "v", "link": "https://youtube.com/watch?v=1", "channel": {"name": "Chan"},
             "duration": "3:10"}]}))
        resp = await self.client(session).videos("cats")
        self.assertEqual((resp.items[0].source, resp.items[0].duration), ("Chan", "3:10"))

        items = parse_news({"news_results": [
            {"title": "n1", "link": "https://n1.com", "source": {"name": "BBC"}, "date": "1h"},
            {"stories": [{"title": "s1", "link": "https://s1.com", "source": {"name": "CNN"}}]}]}, 10)
        self.assertEqual([i.source for i in items], ["BBC", "CNN"])

    async def test_no_results_is_empty_not_error(self):
        session = FakeSession(FakeResponse(200, {"error": "Google hasn't returned any results for this query."}))
        resp = await self.client(session).web("zzzzqqqq")
        self.assertEqual(resp.items, [])
        self.assertIn("لم أجد", "".join(format_response_html(resp)))

    async def test_errors(self):
        cases = [
            (FakeResponse(401, {"error": "Invalid API key"}), "إعدادات"),
            (FakeResponse(429, {"error": "rate"}), "حصة"),
            (FakeResponse(200, {"error": "Your account has run out of searches."}), "حصة"),
            (FakeResponse(500, None, json_error=True), "فشل"),
            (asyncio.TimeoutError(), "مهلة"),
            (ClientError("x"), "الاتصال"),
        ]
        for item, expected in cases:
            with self.assertRaises(SearchError) as cm:
                await self.client(FakeSession(item)).web("q")
            self.assertIn(expected, cm.exception.user_message)

    async def test_disabled_without_key(self):
        c = self.client(FakeSession(), key="")
        self.assertFalse(c.enabled)
        with self.assertRaises(SearchError):
            await c.web("q")

    async def test_reverse_image_and_lens_fallback(self):
        good = {"image_results": [{"title": "R", "link": "https://r.com", "snippet": "s"}]}
        session = FakeSession(FakeResponse(200, good))
        resp = await self.client(session).reverse_image("https://img/1.jpg")
        self.assertEqual(session.calls[0][2]["params"]["engine"], "google_reverse_image")
        self.assertEqual(session.calls[0][2]["params"]["image_url"], "https://img/1.jpg")
        self.assertEqual(resp.items[0].url, "https://r.com")

        lens = {"visual_matches": [{"title": "L", "link": "https://l.com"}]}
        session = FakeSession(FakeResponse(200, {}), FakeResponse(200, lens))
        resp = await self.client(session).reverse_image("https://img/1.jpg")
        self.assertEqual(session.calls[1][2]["params"]["engine"], "google_lens")
        self.assertEqual(resp.items[0].url, "https://l.com")

        session = FakeSession(FakeResponse(401, {"error": "Invalid API key"}),
                              FakeResponse(401, {"error": "Invalid API key"}))
        with self.assertRaises(SearchError):
            await self.client(session).reverse_image("https://img/1.jpg")

    async def test_upload_temp_image(self):
        session = FakeSession(FakeResponse(200, text_data="https://litter.catbox.moe/abc.jpg\n"))
        self.assertEqual(await upload_temp_image(session, b"123"), "https://litter.catbox.moe/abc.jpg")
        with self.assertRaises(SearchError):
            await upload_temp_image(FakeSession(FakeResponse(500, text_data="error")), b"1")
        with self.assertRaises(SearchError):
            await upload_temp_image(FakeSession(FakeResponse(200, text_data="not a url")), b"1")

    def test_formatting_escapes_html(self):
        data = {"organic_results": [{"title": "<b>Evil & co</b>", "link": "https://x.com/?a=1&b=\"2\"",
                                     "snippet": "<script>alert(1)</script>"}]}
        items, answer = parse_web(data, 5)
        text = "".join(format_response_html(SearchResponse("web", "q<>", items, answer)))
        self.assertNotIn("<script>", text)
        self.assertNotIn("<b>Evil", text)
        self.assertIn("&lt;b&gt;Evil &amp; co", text)
        self.assertIn("&quot;2&quot;", text)

    def test_ai_context_is_bounded(self):
        items, _ = parse_web({"organic_results": [
            {"title": "T" * 100, "link": f"https://x.com/{i}", "snippet": "s" * 300} for i in range(50)]}, 50)
        ctx = build_ai_context(SearchResponse("web", "q", items), max_chars=1000)
        self.assertLessEqual(len(ctx), 1000)


# ------------------------------------------------------------------- core
class CoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings = make_settings(self.tmp_path)
        self.db = Database(self.settings.db_path)
        await self.db.init()
        self.owner = User(1, "owner", "Owner")
        self.alice = User(2, "alice", "Alice")
        self.bob = User(3, "bob", "Bob")

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    def ctx(self, ai=None, search=None, **setting_overrides):
        settings = make_settings(self.tmp_path, **setting_overrides) if setting_overrides else self.settings
        return AppContext(
            settings=settings, db=self.db, ai=ai or FakeAI(), search=search or FakeSearch(),
            session=None,  # type: ignore[arg-type]
            antispam=AntiSpam(settings.min_interval_seconds, settings.burst_max,
                              settings.burst_window_seconds, settings.cooldown_seconds),
        )

    async def test_default_prompt_used_with_date(self):
        ai = FakeAI(["hello"])
        ctx = self.ctx(ai)
        result = await core.chat(ctx, self.alice, "hi")
        self.assertEqual(result.text, "hello")
        system = ai.requests[0][0]
        self.assertEqual(system["role"], "system")
        self.assertTrue(system["content"].startswith(DEFAULT_SYSTEM_PROMPT))
        self.assertIn("Current date", system["content"])

    async def test_custom_prompt_owner_only_and_used_every_request(self):
        ai = FakeAI(["r1", "r2"])
        ctx = self.ctx(ai)
        for fn in (core.set_prompt, ):
            with self.assertRaises(UserFacingError) as cm:
                await fn(ctx, self.alice, "evil prompt")
            self.assertIn("لمالك", cm.exception.text)
        with self.assertRaises(UserFacingError):
            await core.show_prompt(ctx, self.alice)
        with self.assertRaises(UserFacingError):
            await core.reset_prompt(ctx, self.alice)

        self.assertEqual(await core.set_prompt(ctx, self.owner, "You are a pirate."), 17)
        prompt, custom = await core.show_prompt(ctx, self.owner)
        self.assertEqual((prompt, custom), ("You are a pirate.", True))

        await core.chat(ctx, self.alice, "one")
        await core.chat(ctx, self.bob, "two")
        for req in ai.requests:
            self.assertTrue(req[0]["content"].startswith("You are a pirate."))

        # survives a "restart" (new Database on the same file)
        db2 = Database(self.settings.db_path)
        await db2.init()
        ctx2 = AppContext(settings=self.settings, db=db2, ai=ai, search=FakeSearch(), session=None,  # type: ignore[arg-type]
                          antispam=ctx.antispam)
        self.assertEqual(await core.get_system_prompt(ctx2), ("You are a pirate.", True))
        await db2.close()

        self.assertTrue(await core.reset_prompt(ctx, self.owner))
        self.assertEqual(await core.get_system_prompt(ctx), (DEFAULT_SYSTEM_PROMPT, False))

    async def test_set_prompt_validation(self):
        ctx = self.ctx()
        with self.assertRaises(UserFacingError):
            await core.set_prompt(ctx, self.owner, "   ")
        with self.assertRaises(UserFacingError) as cm:
            await core.set_prompt(ctx, self.owner, "x" * 501)
        self.assertIn("طويل", cm.exception.text)

    async def test_memory_separate_per_user_and_clear(self):
        ai = FakeAI(["a1", "a2", "b1"])
        ctx = self.ctx(ai)
        await core.chat(ctx, self.alice, "alice-1")
        await core.chat(ctx, self.alice, "alice-2")
        await core.chat(ctx, self.bob, "bob-1")
        second_alice = ai.requests[1]
        self.assertEqual([m["content"] for m in second_alice[1:]], ["alice-1", "a1", "alice-2"])
        bob_req = ai.requests[2]
        self.assertEqual([m["content"] for m in bob_req[1:]], ["bob-1"])
        self.assertEqual(await core.clear_memory(ctx, self.alice), 4)
        self.assertEqual(await self.db.count_messages(self.bob.id), 2)

    async def test_daily_limit_owner_exempt_and_refund_on_error(self):
        ctx = self.ctx(FakeAI(["ok"]))
        for i in range(3):
            await core.chat(ctx, self.alice, f"m{i}")
        with self.assertRaises(UserFacingError) as cm:
            await core.chat(ctx, self.alice, "one too many")
        self.assertIn("للحد اليومي", cm.exception.text)
        for i in range(6):  # owner is exempt
            await core.chat(ctx, self.owner, f"o{i}")

        # failed AI calls must not eat the quota
        bad_ctx = self.ctx(FakeAI(error=AIError("friendly", "secret detail")))
        for _ in range(5):
            with self.assertRaises(UserFacingError) as cm:
                await core.chat(bad_ctx, self.bob, "hi")
            self.assertEqual(cm.exception.text, "friendly")  # detail not leaked
        self.assertEqual(await self.db.get_usage(self.bob.id, bad_ctx.day(), "ai"), 0)
        self.assertEqual(await self.db.count_messages(self.bob.id), 0)  # nothing saved on failure

        with self.assertRaises(UserFacingError) as cm:
            await core.chat(bad_ctx, self.owner, "hi")
        self.assertIn("secret detail", cm.exception.text)  # owner sees detail

    async def test_unexpected_exception_is_wrapped(self):
        ctx = self.ctx(FakeAI(error=RuntimeError("kaboom")))
        with self.assertRaises(UserFacingError) as cm:
            await core.chat(ctx, self.alice, "hi")
        self.assertNotIn("kaboom", cm.exception.text)
        self.assertEqual(await self.db.get_usage(self.alice.id, ctx.day(), "ai"), 0)

    async def test_input_validation(self):
        ctx = self.ctx()
        with self.assertRaises(UserFacingError):
            await core.chat(ctx, self.alice, "   ")
        with self.assertRaises(UserFacingError) as cm:
            await core.chat(ctx, self.alice, "x" * 4001)
        self.assertIn("طويلة", cm.exception.text)

    async def test_spam_protection(self):
        ctx = self.ctx(FakeAI(["ok"]), min_interval_seconds=60, burst_max=100)
        await core.chat(ctx, self.alice, "first")
        with self.assertRaises(UserFacingError) as cm:
            await core.chat(ctx, self.alice, "second too fast")
        self.assertIsNone(cm.exception.text)  # silently ignored
        await core.chat(ctx, self.owner, "owner a")
        await core.chat(ctx, self.owner, "owner b")  # owner never throttled

        ctx = self.ctx(FakeAI(["ok"]), min_interval_seconds=0, burst_max=2, cooldown_seconds=60)
        await core.chat(ctx, self.bob, "1")
        await core.chat(ctx, self.bob, "2")
        with self.assertRaises(UserFacingError) as cm:
            await core.chat(ctx, self.bob, "3")
        self.assertIn("إيقافك مؤقتاً", cm.exception.text)

    async def test_concurrent_message_is_rejected(self):
        gate = asyncio.Event()

        class SlowAI(FakeAI):
            async def chat(self, messages):
                await gate.wait()
                return "slow"

        ctx = self.ctx(SlowAI())
        first = asyncio.create_task(core.chat(ctx, self.alice, "first"))
        await asyncio.sleep(0.05)
        with self.assertRaises(UserFacingError) as cm:
            await core.chat(ctx, self.alice, "second")
        self.assertIn("أعالج", cm.exception.text)
        gate.set()
        self.assertEqual((await first).text, "slow")

    async def test_chat_with_search_injects_context_but_memory_stays_clean(self):
        items, answer = parse_web({"organic_results": [
            {"title": "News", "link": "https://n.com", "snippet": "fresh facts"}]}, 5)
        search = FakeSearch(SearchResponse("web", "q", items, answer))
        ai = FakeAI(["answer"])
        ctx = self.ctx(ai, search)
        result = await core.chat(ctx, self.alice, "what happened?", use_search=True)
        self.assertTrue(result.searched)
        sent = ai.requests[0][-1]["content"]
        self.assertIn("what happened?", sent)
        self.assertIn("https://n.com", sent)
        history = await self.db.get_history(self.alice.id, 20, 10000)
        self.assertEqual(history[0]["content"], "what happened?")
        self.assertEqual(await self.db.get_usage(self.alice.id, ctx.day(), "search"), 1)

    async def test_video_intent_uses_video_engine_and_only_real_sources_are_shown(self):
        items = [SearchItem(title="Liverpool vs Arsenal highlights", url="https://official.example/video", snippet="Match highlights")]
        search = FakeSearch(SearchResponse("videos", "مقاطع ليفربول ضد أرسنال", items))
        ai = FakeAI(["شاهد الملخص هنا https://fake.example/not-real"])
        ctx = self.ctx(ai, search)
        result = await core.chat(ctx, self.alice, "مقاطع ليفربول ضد أرسنال", use_search=True)
        self.assertEqual(search.calls[0][0], "videos")
        self.assertNotIn("fake.example", result.text)
        self.assertIsNotNone(result.search_response)
        self.assertEqual(result.search_response.items[0].url, "https://official.example/video")
        self.assertIn("SEARCH GROUNDING RULES", ai.requests[0][0]["content"])

    async def test_chat_survives_search_failure_and_limit(self):
        search = FakeSearch(error=SearchError("x", "boom"))
        ctx = self.ctx(FakeAI(["answer"]), search)
        result = await core.chat(ctx, self.alice, "q", use_search=True)
        self.assertEqual(result.text, "answer")
        self.assertFalse(result.searched)
        self.assertTrue(result.notes)
        self.assertEqual(await self.db.get_usage(self.alice.id, ctx.day(), "search"), 0)

        ctx = self.ctx(FakeAI(["answer"]), FakeSearch(SearchResponse("web", "q")), daily_search_limit=1)
        await self.db.try_consume(self.bob.id, ctx.day(), "search", 1)
        result = await core.chat(ctx, self.bob, "q", use_search=True)
        self.assertEqual(result.text, "answer")
        self.assertTrue(any("للحد" in n for n in result.notes))

    async def test_run_search_flow(self):
        resp = SearchResponse("images", "cats")
        search = FakeSearch(resp)
        ctx = self.ctx(search=search)
        self.assertIs(await core.run_search(ctx, self.alice, "images", "cats"), resp)
        self.assertEqual(search.calls, [("images", "cats")])
        with self.assertRaises(UserFacingError):
            await core.run_search(ctx, self.alice, "images", "   ")
        await core.run_search(ctx, self.alice, "images", "dogs")
        with self.assertRaises(UserFacingError) as cm:  # limit is 2
            await core.run_search(ctx, self.alice, "images", "birds")
        self.assertIn("للحد اليومي", cm.exception.text)

    async def test_run_search_reverse_with_factory_and_failure_refund(self):
        search = FakeSearch(SearchResponse("reverse", "u"))
        ctx = self.ctx(search=search)

        async def factory():
            return "https://img/1.jpg"

        await core.run_search(ctx, self.alice, "reverse", factory)
        self.assertEqual(search.calls, [("reverse", "https://img/1.jpg")])

        async def broken_factory():
            raise SearchError("upload failed", "detail")

        with self.assertRaises(UserFacingError) as cm:
            await core.run_search(ctx, self.bob, "reverse", broken_factory)
        self.assertEqual(cm.exception.text, "upload failed")
        self.assertEqual(await self.db.get_usage(self.bob.id, ctx.day(), "search"), 0)

    async def test_search_disabled(self):
        search = FakeSearch()
        search.enabled = False
        ctx = self.ctx(search=search)
        with self.assertRaises(UserFacingError) as cm:
            await core.run_search(ctx, self.alice, "web", "q")
        self.assertIn("SerpApi", cm.exception.text)
        result = await core.chat(ctx, self.alice, "hi", use_search=True)
        self.assertTrue(result.notes)

    async def test_status_and_autosearch(self):
        ctx = self.ctx()
        await core.set_autosearch(ctx, self.alice, True)
        self.assertTrue(await core.get_autosearch(ctx, self.alice))
        self.assertFalse(await core.get_autosearch(ctx, self.bob))
        await core.chat(ctx, self.alice, "hi")
        text = await core.build_status(ctx, self.alice)
        self.assertIn("1 / 3", text)
        self.assertNotIn("معلومات المالك", text)
        owner_text = await core.build_status(ctx, self.owner)
        self.assertIn("معلومات المالك", owner_text)
        self.assertIn("∞", owner_text)


if __name__ == "__main__":
    unittest.main()
