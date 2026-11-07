#!/usr/bin/env python3
"""LC Insight hot-news watcher (owner, Nov 6 2026: hot news must be up within ~1 hour, not 10+).

Free: runs on GitHub Actions, no AI. Every 10 minutes it checks public primary-data feeds and puts TIPS on a queue
(branch hot-queue, file queue.json). The hourly Claude "breaking" run verifies each tip on primary sources, writes
the story, and records handled tip ids in done.json (this script never touches done.json). A tip is never published as-is.

Signals:
  - price: BTC/ETH move >= 3% in 1h, a top-100 coin >= 10% in 1h or >= 25% in 24h (CoinGecko)
  - hack: a new DefiLlama hacks entry >= $1M
  - regulator: new item on any government / regulator channel in gov_sources.json that mentions crypto (many languages)
  - trending: a coin new to CoinGecko's trending top 3 with >= 15% 24h move
"""
import json, os, re, subprocess, sys, time, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone

UA = {'User-Agent': 'LCInsight-HotWatch/1.0 (+https://lcinsight.net)', 'Accept': 'application/json, text/xml, */*'}
LOOP_MIN, RUN_FOR_MIN = 10, int(os.environ.get('RUN_FOR_MIN', '330'))
STATE = 'hotq'   # worktree dir for branch hot-queue

def get(url, js=True):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
    return json.loads(r) if js else r

def now(): return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def signals(seen):
    out = []
    def add(key, kind, hint, url, data):
        if key in seen: return
        seen[key] = now(); out.append({'id': key, 'kind': kind, 'hint': hint, 'source': url, 'data': data, 'found': now()})
    # prices
    try:
        mk = get('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&price_change_percentage=1h,24h')
        day = datetime.now(timezone.utc).strftime('%Y%m%d%H')
        for c in mk:
            h1, h24 = c.get('price_change_percentage_1h_in_currency') or 0, c.get('price_change_percentage_24h_in_currency') or 0
            big = c['symbol'] in ('btc', 'eth')
            if (big and abs(h1) >= 3) or (not big and abs(h1) >= 10) or (not big and abs(h24) >= 25):
                add(f"price:{c['id']}:{day[:8]}:{'up' if (h1 or h24) > 0 else 'down'}", 'price',
                    f"{c['name']} ({c['symbol'].upper()}) {h1:+.1f}% in 1h, {h24:+.1f}% in 24h, now ${c['current_price']:,}",
                    f"https://www.coingecko.com/en/coins/{c['id']}", {'h1': h1, 'h24': h24, 'price': c['current_price'], 'mcap_rank': c.get('market_cap_rank')})
    except Exception as e: print('coingecko markets:', e)
    try:
        tr = get('https://api.coingecko.com/api/v3/search/trending')['coins'][:3]
        for t in tr:
            it = t['item']; ch = ((it.get('data') or {}).get('price_change_percentage_24h') or {}).get('usd') or 0
            if abs(ch) >= 15:
                add(f"trend:{it['id']}:{datetime.now(timezone.utc):%Y%m%d}", 'trending', f"{it['name']} ({it['symbol']}) trending #{it.get('score',0)+1} on CoinGecko, {ch:+.1f}% 24h",
                    f"https://www.coingecko.com/en/coins/{it['id']}", {'ch24': ch})
    except Exception as e: print('coingecko trending:', e)
    # hacks
    try:
        hk = get('https://api.llama.fi/hacks')
        recent = [h for h in hk if h.get('date') and time.time() - h['date'] < 3 * 86400 and (h.get('amount') or 0) >= 1e6]
        for h in recent:
            add(f"hack:{h.get('name')}:{h['date']}", 'hack', f"{h.get('name')} hacked/exploited, ~${h['amount']/1e6:.1f}M ({h.get('classification') or h.get('technique') or ''})",
                h.get('source') or 'https://defillama.com/hacks', {'amount': h['amount'], 'chain': h.get('chain'), 'technique': h.get('technique')})
    except Exception as e: print('defillama hacks:', e)
    # government / regulator channels: U.S. + countries where many people use crypto (owner, Nov 7 2026)
    KW = (r'crypto|virtual (asset|currenc)|digital (asset|currenc)|stablecoin|bitcoin|blockchain|\btokeni[sz]|\bVASP|'
          r'\\b(spot )?(bitcoin|ether|ethereum|solana|xrp|dogecoin|litecoin|cardano|avalanche|hedera|polkadot|sui|chainlink|injective|staked)\\b.*\\b(ETF|trust|fund)\\b|ransomware|darknet|Garantex|mixer|DPRK|North Korea|tiền mã hóa|tài sản mã hóa|tài sản số|kripto|cripto|'
          r'暗号資産|가상자산|虛擬資產|虚拟资产|数字货币|aset kripto|криптовалют|цифров')
    src = json.load(open(os.path.join(os.path.dirname(__file__), 'gov_sources.json')))['sources']
    for name, kind, url in src:
        try:
            raw = get(url, js=False)
            found = []
            if kind == 'fedreg':
                for d in json.loads(raw).get('results', []): found.append((d.get('title', ''), d.get('html_url', '')))
            elif kind == 'rss' or raw[:200].lstrip().startswith(b'<?xml') or b'<rss' in raw[:300]:
                root = ET.fromstring(raw)
                for it in list(root.iter('item'))[:25] + list(root.iter('{http://www.w3.org/2005/Atom}entry'))[:25]:
                    t = it.findtext('title') or it.findtext('{http://www.w3.org/2005/Atom}title') or ''
                    l = it.findtext('link') or ''
                    if not l:
                        le = it.find('{http://www.w3.org/2005/Atom}link'); l = le.get('href') if le is not None else ''
                    d = it.findtext('description') or ''
                    found.append((t + ' ' + re.sub('<[^>]+>', ' ', d)[:300], l.strip()))
            else:
                page = raw.decode('utf-8', 'ignore'); base = re.match(r'(https?://[^/]+)', url).group(1)
                for href, txt in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>\s*([^<]{20,240}?)\s*</a>', page):
                    found.append((re.sub(r'\s+', ' ', txt).strip(), href if href.startswith('http') else base + ('' if href.startswith('/') else '/') + href))
            if f'_warm:{name}' not in seen:   # first look at a channel: remember what is already there, don't flood the queue
                for text, link in found: seen[f"reg:{link}"] = now()
                seen[f'_warm:{name}'] = now(); print(name, 'warmed up with', len(found), 'links'); continue
            for text, link in found:
                if link and re.search(KW, text, re.I) and not re.search(r'cookie|subscribe|privacy policy', text, re.I):
                    add(f"reg:{link}", 'regulator', f"{name}: {text.strip()[:200]}", link, {'source': name})
        except Exception as e: print(name, type(e).__name__, str(e)[:120])
    return out

def git(*a, cwd=STATE): return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)

def setup():
    subprocess.run(['git', 'config', '--global', 'user.name', 'LC Insight bot'])
    subprocess.run(['git', 'config', '--global', 'user.email', 'bot@lcinsight.net'])
    r = subprocess.run(['git', 'fetch', 'origin', 'hot-queue'], capture_output=True, text=True)
    if r.returncode == 0: subprocess.run(['git', 'worktree', 'add', STATE, 'origin/hot-queue'], check=True); git('checkout', '-B', 'hot-queue')
    else:
        subprocess.run(['git', 'worktree', 'add', '--detach', STATE], check=True); git('checkout', '--orphan', 'hot-queue'); git('rm', '-rf', '.')
        json.dump([], open(f'{STATE}/queue.json', 'w')); json.dump({}, open(f'{STATE}/seen.json', 'w'))

def step():
    git('pull', '-q', 'origin', 'hot-queue')
    q = json.load(open(f'{STATE}/queue.json')) if os.path.exists(f'{STATE}/queue.json') else []
    seen = json.load(open(f'{STATE}/seen.json')) if os.path.exists(f'{STATE}/seen.json') else {}
    new = signals(seen)
    if not new: print(now(), 'no new tips'); return
    q = [x for x in q if (time.time() - datetime.strptime(x['found'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()) < 3 * 86400] + new
    seen = {k: v for k, v in seen.items() if k.startswith('_warm:') or (time.time() - datetime.strptime(v, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()) < 14 * 86400}
    json.dump(q, open(f'{STATE}/queue.json', 'w'), indent=1); json.dump(seen, open(f'{STATE}/seen.json', 'w'), indent=0)
    git('add', '-A'); git('commit', '-qm', f'{len(new)} hot tips'); r = git('push', '-q', 'origin', 'hot-queue')
    print(now(), len(new), 'tips:', '; '.join(x['hint'] for x in new), r.stderr[-200:])

if __name__ == '__main__':
    setup(); t0 = time.time()
    while True:
        try: step()
        except Exception as e: print('step error:', e)
        if (time.time() - t0) / 60 + LOOP_MIN > RUN_FOR_MIN or os.environ.get('ONCE'): break
        time.sleep(LOOP_MIN * 60)
