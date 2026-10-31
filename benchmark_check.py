import time, concurrent.futures
from core.tiktok_checker import fetch_channel_info

users = ['tiktok', 'charlidamelio', 'khaby.lame', 'addisonre', 'bts.bighitofficial']

print(f"=== Pipeline: {len(users)} kênh, 5 workers, rate-limited 1 req/s ===")
t = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
    results = list(ex.map(fetch_channel_info, users))
elapsed = time.time() - t
ok = sum(1 for r in results if r.get("status") == "ok")
for r in results:
    name = r.get("username", "?")
    fol  = r.get("followers_fmt", "N/A")
    st   = r.get("status")
    err  = r.get("error", "")
    print(f"  @{name}: {fol} [{st}] {err}")
print(f"\nTotal: {elapsed:.1f}s | OK: {ok}/{len(users)}")
print(f"Lý thuyết: {len(users)*1.15+10:.0f}s | Thực tế: {elapsed:.1f}s")
