#!/usr/bin/env python3
"""Post new LC Insight stories to the Telegram channel.
Compares posts.json in this push with the previous commit; sends each new story as photo + caption + button.
Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL (e.g. @lcinsight). Limits: 6 news + 2 guides per push."""
import re, json, os, urllib.error, subprocess, sys, time, urllib.parse, urllib.request

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT = os.environ.get('TELEGRAM_CHANNEL', '').strip()
BEFORE = os.environ.get('BEFORE', '').strip()
MODE = os.environ.get('MODE', 'new')          # "new" (on push) or "test" (manual: post the latest story once)
MAX_NEWS, MAX_GUIDES = 6, 2

def load(rev):
    try:
        return json.loads(subprocess.run(['git', 'show', f'{rev}:posts.json'], capture_output=True, text=True, check=True).stdout)
    except Exception:
        return None

def esc(s): return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def wait_live(url, tries=12):
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        print(f'{method} -> HTTP {e.code}: {body}')   # Telegram's own reason (never contains the token)
        raise

CAT_EMOJI = {"Security": "🛡️", "Markets": "📊", "Policy": "⚖️", "Exchanges": "🏦", "DeFi": "🌊", "Infrastructure": "⚙️",
             "Projects": "🧩", "AI & RWA": "🤖", "Culture": "🎭", "Guides": "📚", "Guide": "📚"}
HOOK = [(("hack", "exploit", "stolen", "drain", "attack", "theft", "lost"), "🚨"), (("froze", "freeze", "frozen"), "🧊"),
        (("airdrop", "reward"), "🎁"), (("launch", "upgrade", "mainnet", "faster", "tge"), "🚀"),
        (("sec ", "law ", "laws ", "court", "rules ", "ban ", "bans ", "license", "tax ", "regulator"), "⚖️"), (("burn",), "🔥"),
        (("jump", "surge", "soar", "record high", "rall", "inflow"), "📈"), (("fall", "drop", "plunge", "outflow", "crash"), "📉"),
        (("billion",), "💥"), (("whale",), "🐋"), (("bitcoin", "btc"), "🟠"), (("ethereum", "eth "), "💎")]
def hook(p):
    if p.get('guide'): return '📚'
    t = p['title'].lower()
    return next((e for keys, e in HOOK if any(re.search(r'\b' + re.escape(k.strip()) + (r'\b' if k.endswith(' ') else ''), t) for k in keys)), '⚡')

def post(p):
    label = 'Guide' if p.get('guide') else p.get('category', 'News')
    tags = ' '.join(p.get('hashtags', []))
    head = '🔥 HOT' if label == 'Security' and not p.get('guide') else ''
    cap = (f"{hook(p)} <b>{esc(p['title'])}</b>\n\n"
           f"👉 {esc(p['dek'])}\n\n"
           f"{CAT_EMOJI.get(label, '📰')} <i>{esc(label)}</i> · LC Insight{(' · ' + head) if head else ''}\n{esc(tags)}")
    kb = json.dumps({"inline_keyboard": [[{"text": "📖 Read the full story", "url": p['url']}]]})
    try:
        return api('sendPhoto', {'chat_id': CHAT, 'photo': p['image'], 'caption': cap[:1024], 'parse_mode': 'HTML', 'reply_markup': kb})
    except Exception as e:
        print('photo failed, sending text:', e)
        return api('sendMessage', {'chat_id': CHAT, 'text': cap + f"\n\n{p['url']}", 'parse_mode': 'HTML', 'reply_markup': kb})

def main():
    if not TOKEN or not CHAT:
        print('Telegram secrets not set; skipping.'); return
    now = load('HEAD') or []
    if MODE == 'test':
        todo = now[:1]
    else:
        prev = load(BEFORE) if BEFORE and set(BEFORE) != {'0'} else None
        old = {p['slug'] for p in prev} if prev is not None else None
        if old is None:
            print('No previous posts.json (first run); not posting the back catalogue.'); return
        # only genuinely fresh stories: a story that drops out and comes back (rollback, restore) is not re-posted
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
        seen = set()
        for rev in subprocess.run(['git', 'rev-list', '--max-count=40', 'HEAD~1', '--', 'posts.json'], capture_output=True, text=True).stdout.split():
            seen |= {p['slug'] for p in (load(rev) or [])}
        new = [p for p in now if p['slug'] not in old and p['slug'] not in seen
               and datetime.fromisoformat(p['published']) >= cutoff]
        news = [p for p in new if not p.get('guide')][:MAX_NEWS]
        guides = [p for p in new if p.get('guide')][:MAX_GUIDES]
        todo = sorted(news + guides, key=lambda p: p['published'])
        skipped = len(new) - len(todo)
        if skipped: print(f'{skipped} more new stories not posted this time (limit per push).')
    if not todo: print('Nothing new to post.'); return
    ch = CHAT if CHAT.startswith('@') or CHAT.lstrip('-').isdigit() else '@' + CHAT.rsplit('/', 1)[-1]
    globals()['CHAT'] = ch
    try:
        info = api('getChat', {'chat_id': ch}); print('channel ok:', info['result'].get('title'))
    except Exception:
        print('Channel check failed. TELEGRAM_CHANNEL must be the public @username of the channel, and the bot must be an admin there.'); sys.exit(1)
    print('site reachable:', wait_live(todo[-1]['url']))
    for p in todo:
        r = post(p); print('posted' if r.get('ok') else 'FAILED', p['slug'], '' if r.get('ok') else r)
        time.sleep(4)

if __name__ == '__main__':
    main()
