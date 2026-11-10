#!/usr/bin/env python3
"""Post new LC Insight stories to the Telegram channel.
Drip mode: queues new hot stories and posts one every ~35-40 minutes (07:00-23:30 VN), photo + caption + button.
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
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'LCInsight-Telegram/1.0'}), timeout=15) as r:
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
             "Projects": "🧩", "AI & RWA": "🤖", "Culture": "🎭", "Guides": "📚", "Guide": "📚", "Airdrops": "🪂"}
HOOK = [(("hack", "exploit", "stolen", "drain", "attack", "theft", "lost"), "🚨"), (("froze", "freeze", "frozen"), "🧊"),
        (("airdrop", "reward", "claim", "snapshot", "points"), "🎁"), (("launch", "upgrade", "mainnet", "faster", "tge"), "🚀"),
        (("sec ", "law ", "laws ", "court", "rules ", "ban ", "bans ", "license", "tax ", "regulator"), "⚖️"), (("burn",), "🔥"),
        (("jump", "surge", "soar", "record high", "rall", "inflow"), "📈"), (("fall", "drop", "plunge", "outflow", "crash"), "📉"),
        (("billion",), "💥"), (("whale",), "🐋"), (("bitcoin", "btc"), "🟠"), (("ethereum", "eth "), "💎")]
def hook(p):
    if p.get('guide'): return '📚'
    t = p['title'].lower()
    return next((e for keys, e in HOOK if any(re.search(r'\b' + re.escape(k.strip()) + (r'\b' if k.endswith(' ') else ''), t) for k in keys)), '⚡')

HOT_CATS = {"Security", "Projects", "Airdrops"}
HOT_HOOKS = {"🔥", "🚨", "🧊", "🎁", "🚀", "💥", "🐋", "📈", "📉"}
def is_hot(p):
    return bool(p.get('hot')) or p.get('category') in HOT_CATS or hook(p) in HOT_HOOKS

def post(p):
    label = 'Guide' if p.get('guide') else p.get('category', 'News')
    tags = ' '.join(p.get('hashtags', []))
    head = '🔥 HOT' if not p.get('guide') else ''
    cap = (f"{hook(p)} <b>{esc(p['title'])}</b>\n\n"
           f"👉 {esc(p['dek'])}\n\n"
           f"{CAT_EMOJI.get(label, '📰')} <i>{esc(label)}</i> · LC Insight{(' · ' + head) if head else ''}\n{esc(tags)}")
    kb = json.dumps({"inline_keyboard": [[{"text": "📖 Read the full story", "url": p['url']}]]})
    try:
        return api('sendPhoto', {'chat_id': CHAT, 'photo': p['image'], 'caption': cap[:1024], 'parse_mode': 'HTML', 'reply_markup': kb})
    except Exception as e:
        print('photo failed, sending text:', e)
        return api('sendMessage', {'chat_id': CHAT, 'text': cap + f"\n\n{p['url']}", 'parse_mode': 'HTML', 'reply_markup': kb})

STATE_BRANCH = 'tg-state'
GAP_MIN = 38                      # at least this many minutes between two channel posts
def vn_now():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone.utc) + timedelta(hours=7)
def load_state():
    subprocess.run(['git', 'fetch', '-q', 'origin', STATE_BRANCH], capture_output=True)
    r = subprocess.run(['git', 'show', f'origin/{STATE_BRANCH}:posted.json'], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None
def save_state(st):
    import tempfile
    d = tempfile.mkdtemp()
    g = lambda *a: subprocess.run(['git', '-C', d, *a], check=True, capture_output=True)
    url = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True).stdout.strip()
    hdr = subprocess.run(['git', 'config', '--get-regexp', 'http.*extraheader'], capture_output=True, text=True).stdout.split(' ', 1)
    g('init', '-q'); g('remote', 'add', 'origin', url)
    if len(hdr) == 2: g('config', hdr[0], hdr[1].strip())
    g('config', 'user.name', 'lc-telegram'); g('config', 'user.email', 'actions@users.noreply.github.com')
    g('checkout', '-q', '-b', STATE_BRANCH)
    open(f'{d}/posted.json', 'w').write(json.dumps(st, indent=0))
    g('add', 'posted.json'); g('commit', '-q', '-m', 'Telegram state'); g('push', '-q', '-f', 'origin', STATE_BRANCH)

def step():
    """Drip mode (owner, November 4, 2026): Telegram readers want fresh news all day, so new hot stories are queued
    and posted one at a time, at least GAP_MIN minutes apart, 07:00-23:30 Vietnam time, freshest hot story first."""
    if not TOKEN or not CHAT:
        print('Telegram secrets not set; skipping.'); return
    subprocess.run(['git', 'fetch', '-q', 'origin', 'main'], capture_output=True)
    now = load('origin/main') or load('HEAD') or []
    ch = CHAT if CHAT.startswith('@') or CHAT.lstrip('-').isdigit() else '@' + CHAT.rsplit('/', 1)[-1]
    globals()['CHAT'] = ch
    if MODE == 'test':
        r = post(now[0]); print('posted' if r.get('ok') else 'FAILED', now[0]['slug']); return
    from datetime import datetime, timezone, timedelta
    st = load_state()
    if st is None:   # first run of drip mode: everything already live counts as posted (no back catalogue flood)
        st = {'posted': [p['slug'] for p in now], 'last': 0}
        save_state(st); print('state created with', len(st['posted']), 'stories'); return
    vn = vn_now(); mins = vn.hour * 60 + vn.minute
    if not (7 * 60 <= mins <= 23 * 60 + 30): print('quiet hours (VN)', vn.strftime('%H:%M')); return
    if time.time() - st.get('last', 0) < GAP_MIN * 60: print('too soon since last post'); return 'soon'
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    NEW_ART = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)
    done = set(st['posted'])
    queue = [p for p in now if p['slug'] not in done and not p.get('guide') and is_hot(p)
             and datetime.fromisoformat(p['published']) >= cutoff
             and datetime.fromisoformat(p['published']) >= NEW_ART]   # owner, Nov 10: only stories with the new 3D scene art
    if not queue: print('queue empty'); return 'empty'
    queue.sort(key=lambda p: (bool(p.get('hot')), p['published']), reverse=True)
    p = queue[0]
    try:
        info = api('getChat', {'chat_id': ch}); print('channel ok:', info['result'].get('title'))
    except Exception:
        print('Channel check failed. TELEGRAM_CHANNEL must be the public @username of the channel, and the bot must be an admin there.'); sys.exit(1)
    if not wait_live(p['url'], tries=4): print('page not live yet, retry soon'); return 'wait'
    r = post(p); ok = bool(r.get('ok')); print('posted' if ok else 'FAILED', p['slug'], f'({len(queue) - 1} left in queue)')
    if ok:
        st['posted'] = (st['posted'] + [p['slug']])[-3000:]; st['last'] = time.time(); save_state(st); return 'posted'

def main():
    # one job keeps dripping: post, wait GAP_MIN, repeat, until the queue is empty, quiet hours, or ~5.5 h
    t0 = time.time()
    while True:
        r = step()
        if r not in ('posted', 'soon', 'wait') or time.time() - t0 > 5.5 * 3600: break
        time.sleep(GAP_MIN * 60 + 30 if r == 'posted' else 300)

if __name__ == '__main__':
    main()
