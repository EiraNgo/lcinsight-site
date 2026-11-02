#!/usr/bin/env python3
"""Post new LC Insight stories to the Telegram channel.
Compares posts.json in this push with the previous commit; sends each new story as photo + caption + button.
Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL (e.g. @lcinsight). Limits: 6 news + 2 guides per push."""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT = os.environ.get('TELEGRAM_CHANNEL', '').strip()
BEFORE = os.environ.get('BEFORE', '').strip()
MODE = os.environ.get('MODE', 'new')          # "new" (on push) or "test" (manual: post the latest story once)
MAX_NEWS, MAX_GUIDES = 6, 2

def load(rev):
    try:
        return json.loads(subprocess.run(['git', 'show', f'{rev}:posts.json'], capture_output=True, text=True, check=True).stdout)
    except Exception:
        return []

def esc(s): return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def wait_live(url, tries=40):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=15) as r:
                if r.status == 200: return True
        except Exception:
            pass
        time.sleep(15)
    return False

def api(method, data):
    req = urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/{method}', data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())

def post(p):
    label = 'Guide' if p.get('guide') else p.get('category', 'News')
    tags = ' '.join(p.get('hashtags', []))
    cap = f"<b>{esc(p['title'])}</b>\n\n{esc(p['dek'])}\n\n<i>{esc(label)}</i> · LC Insight\n{esc(tags)}"
    kb = json.dumps({"inline_keyboard": [[{"text": "Read the full story", "url": p['url']}]]})
    try:
        return api('sendPhoto', {'chat_id': CHAT, 'photo': p['image'], 'caption': cap[:1024], 'parse_mode': 'HTML', 'reply_markup': kb})
    except Exception as e:
        print('photo failed, sending text:', e)
        return api('sendMessage', {'chat_id': CHAT, 'text': cap + f"\n\n{p['url']}", 'parse_mode': 'HTML', 'reply_markup': kb})

def main():
    if not TOKEN or not CHAT:
        print('Telegram secrets not set; skipping.'); return
    now = load('HEAD')
    if MODE == 'test':
        todo = now[:1]
    else:
        old = {p['slug'] for p in load(BEFORE)} if BEFORE and set(BEFORE) != {'0'} else None
        if old is None:
            print('No previous posts.json (first run); not posting the back catalogue.'); return
        new = [p for p in now if p['slug'] not in old]
        news = [p for p in new if not p.get('guide')][:MAX_NEWS]
        guides = [p for p in new if p.get('guide')][:MAX_GUIDES]
        todo = sorted(news + guides, key=lambda p: p['published'])
        skipped = len(new) - len(todo)
        if skipped: print(f'{skipped} more new stories not posted this time (limit per push).')
    if not todo: print('Nothing new to post.'); return
    wait_live(todo[-1]['url'])
    for p in todo:
        r = post(p); print('posted' if r.get('ok') else 'FAILED', p['slug'], '' if r.get('ok') else r)
        time.sleep(4)

if __name__ == '__main__':
    main()
