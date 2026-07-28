#!/usr/bin/env python3
"""
Smoke test for check_approvals.py's core resolve logic: an approve/reject
callback_query must move the item out of pending.json and into posted.json
(and, for approve, actually call sendMessage to the public channel).

Runs offline against a fake tg_call — no real network/secrets needed.
Run: python tests/test_check_approvals_resolve.py
"""
import importlib.util
import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "check_approvals.py")


def load_module_with_fake_tg(calls):
    os.environ.setdefault("TG_BOT_TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location("check_approvals", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def fake_tg_call(method, payload):
        calls.append((method, payload))
        if method == "getUpdates":
            return {"result": mod._TEST_UPDATES}
        return {"ok": True, "result": {"message_id": 1}}

    mod.tg_call = fake_tg_call
    return mod


def run_case(name, update, expect_channel_post):
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        mod = load_module_with_fake_tg(calls)
        mod._TEST_UPDATES = [update]

        # redirect state files into the temp dir so this never touches the real repo state
        mod.PENDING_LOG = os.path.join(tmp, "pending.json")
        mod.POSTED_LOG = os.path.join(tmp, "posted.json")
        mod.OFFSET_LOG = os.path.join(tmp, "tg_offset.json")
        mod.PENDING_COMPANIES_LOG = os.path.join(tmp, "pending_companies.json")
        mod.INDEX_HTML = os.path.join(tmp, "index.html")
        with open(mod.INDEX_HTML, "w") as f:
            f.write("const NEWS = [\n];\n")

        pending_id = "42"
        item = {
            "link": "https://example.com/test-article",
            "title": "Test Article",
            "formatted": "Test headline\n\n• one fact",
            "summary": "a summary",
            "date": "2026-07-28",
        }
        with open(mod.PENDING_LOG, "w") as f:
            json.dump({pending_id: item}, f)
        with open(mod.POSTED_LOG, "w") as f:
            json.dump([], f)

        mod.main()

        with open(mod.PENDING_LOG) as f:
            pending_after = json.load(f)
        with open(mod.POSTED_LOG) as f:
            posted_after = json.load(f)

        assert pending_id not in pending_after, f"[{name}] pending_id should be removed from pending.json"
        assert item["link"] in posted_after, f"[{name}] link should be recorded in posted.json"

        sent_to_channel = any(
            c[0] == "sendMessage" and c[1].get("chat_id") == mod.TG_CHAT for c in calls
        )
        assert sent_to_channel == expect_channel_post, (
            f"[{name}] expected channel post={expect_channel_post}, got calls={calls}"
        )

        # regression check for the "nothing happens" UI-feedback bug: a plain
        # DM to Kerf must be attempted regardless of answerCallbackQuery/
        # editMessageReplyMarkup outcome
        confirmed_kerf = any(
            c[0] == "sendMessage" and c[1].get("chat_id") == mod.KERF_CHAT_ID for c in calls
        )
        assert confirmed_kerf, f"[{name}] must send a confirmation DM to Kerf independent of callback UI calls"

        print(f"OK: {name}")


def main():
    run_case(
        "approve",
        {
            "update_id": 1,
            "callback_query": {
                "id": "cbq1",
                "data": "approve:42",
                "message": {"chat": {"id": 221930844}, "message_id": 99},
            },
        },
        expect_channel_post=True,
    )
    run_case(
        "reject",
        {
            "update_id": 1,
            "callback_query": {
                "id": "cbq2",
                "data": "reject:42",
                "message": {"chat": {"id": 221930844}, "message_id": 99},
            },
        },
        expect_channel_post=False,
    )


if __name__ == "__main__":
    main()
