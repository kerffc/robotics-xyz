#!/usr/bin/env python3
"""
Throwaway test script: sends a clearly-labeled TEST approval draft to Kerf's
Telegram, using the exact same pending.json + Approve/Reject mechanism as
post_robotics_news.py, to verify the approval pipeline end-to-end without
depending on a real RSS item showing up.

Delete this script + its workflow once the test is confirmed working.
"""
import json
import os
import time
import urllib.request

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
KERF_CHAT_ID = 221930844

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING_LOG = os.path.join(REPO_ROOT, "scripts", "pending.json")


def tg_call(method, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def load_pending():
    if os.path.exists(PENDING_LOG):
        with open(PENDING_LOG) as f:
            return json.load(f)
    return {}


def save_pending(pending):
    with open(PENDING_LOG, "w") as f:
        json.dump(pending, f, indent=2)


def main():
    pending = load_pending()
    pending_id = f"test{int(time.time())}"
    link = f"https://example.com/pipeline-test-{pending_id}"
    title = "[TEST] Approval pipeline verification"
    formatted = (
        "[TEST] Approval pipeline verification\n\n"
        "• This is a synthetic test message, not real news. Reject it "
        "unless you want a labeled test entry to briefly land in @dailyrobotics."
    )

    tg_call("sendMessage", {
        "chat_id": KERF_CHAT_ID,
        "text": f"<b>{title}</b>\n\n{formatted.split(chr(10), 2)[-1]}\n\nSource: {link}",
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{pending_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{pending_id}"},
            ]]
        },
    })

    pending[pending_id] = {
        "link": link,
        "title": title,
        "formatted": formatted,
        "summary": "Synthetic test of the approval pipeline fix.",
        "date": time.strftime("%Y-%m-%d"),
    }
    save_pending(pending)
    print(f"sent test draft: {pending_id}")


if __name__ == "__main__":
    main()
