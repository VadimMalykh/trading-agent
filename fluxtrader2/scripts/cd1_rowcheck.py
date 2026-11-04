"""Decision CD1's audit: the fingerprint's extent rule read three names as 'changed' after `upgrades bars --fetch` (rows gained INSIDE their old
extent — holes filled by the fetched months). R78's finer statement (`krlist.rowcheck`): every old row, re-derived from the name's pre-existing
zips, is in the slice now with identical prices and volumes. PASS on every name = the ingest stands; else void.
    PYTHONPATH=. python scripts/cd1_rowcheck.py > output/upgrades/rowcheck.json
"""
import json, re, sys
from pathlib import Path
from ft2 import krlist

log = Path("output/logs/upgrades_bars.log").read_text()
rep = json.loads(log[log.index("{"):])
fetched = rep.get("fetch", {})
changed = [c["symbol"] for c in rep["fingerprint"]["changed"]]
out = {"changed_by_extent_rule": changed, "fetched_months": {s: fetched.get(s) for s in changed}, "rowcheck": {}}
import time
from ft2 import data
for s in changed:                                                   # the new files: the zips written by this chain (today), the rest are the OLD ones
    d = data.EXT / "klines" / s
    new = {f.name for f in d.glob(f"{s}-5m-*.zip") if time.time() - f.stat().st_mtime < 6 * 3600}
    out["rowcheck"][s] = krlist.rowcheck(s, new)
out["pass"] = all(r["pass"] for r in out["rowcheck"].values())
print(json.dumps(out, indent=1, default=str))
sys.exit(0 if out["pass"] else 2)
