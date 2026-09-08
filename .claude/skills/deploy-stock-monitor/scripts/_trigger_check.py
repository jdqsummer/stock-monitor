import urllib.request, json
payload = {'code': '600519', 'name': '贵州茅台', 'context': {'current_price': 1299.52, 'industry_category': '白酒', 'total_market_cap': 16320, 'total_shares': 12.56, 'net_profit_parent': 900, 'net_profit_deducted': 890, 'financials': [], 'news': [], 'quote': {}}, 'model': 'deepseek-v4-flash', 'session_id': 'prod-upgrade-test-004'}
req = urllib.request.Request('http://127.0.0.1:8001/trigger', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read())
        print('HTTP', r.status)
        print('degraded:', data.get('degraded'))
        err = data.get('error')
        print('error:', (err[:200] if err else None))
        print('model:', data.get('model'))
        if data.get('result'):
            print('stages:', list(data['result'].keys()))
        if data.get('compaction'):
            print('compaction:', data['compaction'])
        print('usage:', data.get('usage'))
except urllib.error.HTTPError as e:
    print('HTTPError:', e.code, e.read()[:300])
except Exception as e:
    print('Error:', type(e).__name__, str(e)[:300])
