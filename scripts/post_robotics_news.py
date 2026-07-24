#!/usr/bin/env python3
"""
Finds recent robotics funding/news items from RSS feeds, summarizes each into
a headline + bullet format via Claude, posts new ones to the @dailyrobotics
Telegram channel, and appends them to the NEWS array in index.html.

Dedup state lives in scripts/posted.json (committed back to the repo each run).
"""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT = "@dailyrobotics"
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTED_LOG = os.path.join(REPO_ROOT, "scripts", "posted.json")
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")

FEEDS = [
    "https://techcrunch.com/tag/robotics/feed/",
    "https://www.therobotreport.com/feed/",
    "https://spectrum.ieee.org/feeds/topic/robotics.rss",
]

FUNDING_KEYWORDS = re.compile(
    r"\b(raises?|raised|funding|series [a-e]\b|seed round|valuation|invest(s|ed|ment)?|million|billion)\b",
    re.IGNORECASE,
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (robotics-xyz-bot)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feed(xml_bytes):
    items = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc = re.sub("<[^<]+?>", "", desc)
        if title and link:
            items.append({"title": title, "link": link, "summary": desc})
    return items


def load_posted():
    if os.path.exists(POSTED_LOG):
        with open(POSTED_LOG) as f:
            return set(json.load(f))
    return set()


def save_posted(posted):
    with open(POSTED_LOG, "w") as f:
        json.dump(sorted(posted), f, indent=2)


def call_claude(title, summary, link):
    prompt = f"""Write a Telegram post about this robotics/AI funding or industry news item, in this exact format:

<Headline as a plain sentence, no markdown>

• <bullet 1: the key fact/number>
• <bullet 2: context or what it means>
• <bullet 3: a caveat, risk, or unconfirmed detail if any — omit if none exists>

Article title: {title}
Article summary: {summary}
Article URL: {link}

Rules: no em dashes, no marketing language, be factual and slightly skeptical like a analyst brief. If the article isn't about funding/a notable robotics development, respond with exactly SKIP."""

    body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    return resp["content"][0]["text"].strip()


def post_to_telegram(text, link):
    full_text = f"{text}\n\n[Source]({link})"
    body = json.dumps({
        "chat_id": TG_CHAT,
        "text": full_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def append_to_news_array(title, link, date, summary):
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    marker = "const NEWS = ["
    idx = html.index(marker) + len(marker)
    entry = (
        f'\n    {{\n'
        f'      date: "{date}",\n'
        f'      source: "auto",\n'
        f'      title: {json.dumps(title)},\n'
        f'      summary: {json.dumps(summary[:400])},\n'
        f'      url: {json.dumps(link)},\n'
        f'    }},'
    )
    html = html[:idx] + entry + html[idx:]

    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    posted = load_posted()
    new_posts = 0

    for feed_url in FEEDS:
        try:
            items = parse_feed(fetch(feed_url))
        except Exception as e:
            print(f"feed failed: {feed_url}: {e}")
            continue

        for item in items:
            if item["link"] in posted:
                continue
            if not FUNDING_KEYWORDS.search(item["title"] + " " + item["summary"]):
                continue

            try:
                formatted = call_claude(item["title"], item["summary"], item["link"])
            except Exception as e:
                print(f"claude call failed for {item['link']}: {e}")
                continue

            posted.add(item["link"])  # mark seen regardless, so we don't retry bad items forever

            if formatted.strip() == "SKIP":
                continue

            try:
                post_to_telegram(formatted, item["link"])
                print(f"posted: {item['title']}")
                new_posts += 1
            except Exception as e:
                print(f"telegram post failed for {item['link']}: {e}")
                continue

            date = time.strftime("%Y-%m-%d")
            headline = formatted.split("\n")[0].strip()
            append_to_news_array(headline, item["link"], date, item["summary"])

            time.sleep(2)  # avoid hammering telegram / claude

    save_posted(posted)
    print(f"done. {new_posts} new posts.")


if __name__ == "__main__":
    main()
