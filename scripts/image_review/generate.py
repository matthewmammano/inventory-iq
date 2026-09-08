"""Generate a live item-image review page from whatever DB you point it at.

Re-run any time -- it always reflects the current DB, not a frozen snapshot.
No app import needed (plain sqlite3), so any python3 works.

Usage (from repo root):
    python3 scripts/image_review/generate.py [--db instance/inventory_iq.db] [--out scripts/image_review/output.html]

Opens straight in your browser. Fix broken image URLs inline, then click
"Download changes" to save an id->image JSON of just what you edited. Apply
it back with: python3 -m scripts.image_review.apply image_updates.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import webbrowser
from pathlib import Path

TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Item Image Review</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f4f5f7; color: #1a1a1a; }
  header {
    position: sticky; top: 0; z-index: 10; background: #1a1a2e; color: #fff; padding: 14px 20px;
    display: flex; flex-wrap: wrap; gap: 16px; align-items: center; box-shadow: 0 2px 6px rgba(0,0,0,0.2);
  }
  header h1 { font-size: 16px; margin: 0; margin-right: auto; }
  header .stat { font-size: 13px; padding: 4px 10px; border-radius: 12px; background: #2e2e4d; }
  header .stat.broken { background: #7a1f1f; }
  header .stat.ok { background: #1f5c34; }
  header .stat.pending { background: #555; }
  header input[type=text] { padding: 6px 10px; border-radius: 6px; border: none; font-size: 13px; width: 200px; }
  header label { font-size: 13px; display: flex; align-items: center; gap: 4px; }
  .container { padding: 16px 20px 80px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; }
  th, td { padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 13px; text-align: left; vertical-align: middle; }
  th { background: #eceef2; position: sticky; top: 56px; z-index: 5; }
  tr.broken { background: #fff2f2; }
  tr.broken td.status { color: #c0392b; font-weight: 600; }
  tr.ok td.status { color: #1e8449; }
  tr.pending td.status { color: #888; }
  td.id { color: #999; font-family: monospace; width: 50px; }
  td.preview img { width: 64px; height: 64px; object-fit: contain; background: #f0f0f0; border: 1px solid #ddd; border-radius: 4px; }
  tr.broken td.preview img { border-color: #c0392b; }
  td.url input { width: 100%; padding: 5px 7px; font-size: 12px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; }
  tr.broken td.url input { border-color: #c0392b; background: #fff8f8; }
  td.name { font-weight: 600; white-space: nowrap; }
  .row-hidden { display: none; }
  footer {
    position: fixed; bottom: 0; left: 0; right: 0; background: #1a1a2e; padding: 12px 20px;
    display: flex; gap: 10px; align-items: center; box-shadow: 0 -2px 6px rgba(0,0,0,0.2);
  }
  footer button { background: #4a7dff; color: #fff; border: none; padding: 10px 16px; border-radius: 6px; font-size: 13px; cursor: pointer; }
  footer button:hover { background: #3a6ae0; }
</style>
</head>
<body>
<header>
  <h1>Item Image Review (__COUNT__ items)</h1>
  <span class="stat pending" id="stat-pending">checking...</span>
  <span class="stat ok" id="stat-ok">0 ok</span>
  <span class="stat broken" id="stat-broken">0 broken</span>
  <label><input type="checkbox" id="only-broken"> show only broken</label>
  <input type="text" id="search" placeholder="filter by name...">
  <label><input type="checkbox" id="only-changed"> show only edited</label>
</header>
<div class="container">
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Name</th>
        <th style="width:70px">Preview</th>
        <th>Image URL</th>
        <th style="width:70px">Status</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<footer>
  <button id="recheck-all">Recheck all URLs</button>
  <button id="download">Download changes</button>
  <span id="edited-count" style="color:#ccc; font-size:12px;"></span>
</footer>
<script>
const DATA = __DATA__;
DATA.forEach(row => { row.__status = 'pending'; row.__origImage = row.image; });

const tbody = document.getElementById('tbody');

function rowEl(row) {
  const tr = document.createElement('tr');
  tr.className = row.__status;

  const tdId = document.createElement('td');
  tdId.className = 'id';
  tdId.textContent = row.id;

  const tdName = document.createElement('td');
  tdName.className = 'name';
  tdName.textContent = row.name;

  const tdPreview = document.createElement('td');
  tdPreview.className = 'preview';
  const img = document.createElement('img');
  tdPreview.appendChild(img);

  const tdUrl = document.createElement('td');
  tdUrl.className = 'url';
  const input = document.createElement('input');
  input.type = 'text';
  input.value = row.image || '';
  tdUrl.appendChild(input);

  const tdStatus = document.createElement('td');
  tdStatus.className = 'status';

  tr.append(tdId, tdName, tdPreview, tdUrl, tdStatus);

  function setStatus(s) {
    row.__status = s;
    tr.className = s + (row.image !== row.__origImage ? ' edited' : '');
    tdStatus.textContent = s === 'ok' ? 'OK' : s === 'broken' ? 'BROKEN' : '...';
    updateStats();
  }

  function check() {
    setStatus('pending');
    if (!row.image) { setStatus('broken'); img.removeAttribute('src'); return; }
    img.onload = () => setStatus('ok');
    img.onerror = () => setStatus('broken');
    img.src = row.image;
  }

  input.addEventListener('input', () => {
    row.image = input.value;
    clearTimeout(input._t);
    input._t = setTimeout(check, 500);
  });

  tr._check = check;
  tr._matches = (q) => row.name.toLowerCase().includes(q);
  tr._row = row;
  check();
  return tr;
}

const rows = DATA.map(rowEl);
rows.forEach(tr => tbody.appendChild(tr));

function updateStats() {
  let ok = 0, broken = 0, pending = 0;
  DATA.forEach(r => { if (r.__status === 'ok') ok++; else if (r.__status === 'broken') broken++; else pending++; });
  document.getElementById('stat-ok').textContent = ok + ' ok';
  document.getElementById('stat-broken').textContent = broken + ' broken';
  document.getElementById('stat-pending').textContent = pending ? pending + ' checking...' : 'all checked';
  const edited = DATA.filter(r => r.image !== r.__origImage).length;
  document.getElementById('edited-count').textContent = edited + ' edited';
}

function applyFilters() {
  const onlyBroken = document.getElementById('only-broken').checked;
  const onlyChanged = document.getElementById('only-changed').checked;
  const q = document.getElementById('search').value.trim().toLowerCase();
  rows.forEach(tr => {
    let show = true;
    if (onlyBroken && tr._row.__status !== 'broken') show = false;
    if (onlyChanged && tr._row.image === tr._row.__origImage) show = false;
    if (q && !tr._matches(q)) show = false;
    tr.classList.toggle('row-hidden', !show);
  });
}

document.getElementById('only-broken').addEventListener('change', applyFilters);
document.getElementById('only-changed').addEventListener('change', applyFilters);
document.getElementById('search').addEventListener('input', applyFilters);
document.getElementById('recheck-all').addEventListener('click', () => rows.forEach(tr => tr._check()));

document.getElementById('download').addEventListener('click', () => {
  const updates = {};
  DATA.forEach(row => { if (row.image !== row.__origImage) updates[row.id] = row.image; });
  const blob = new Blob([JSON.stringify(updates, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'image_updates.json';
  a.click();
});
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="instance/inventory_iq.db")
    parser.add_argument("--out", default="scripts/image_review/output.html")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    rows = conn.execute("SELECT id, name, image FROM items WHERE active = 1 ORDER BY name").fetchall()
    conn.close()

    data = [{"id": item_id, "name": name, "image": image or ""} for item_id, name, image in rows]
    html = TEMPLATE.replace("__DATA__", json.dumps(data)).replace("__COUNT__", str(len(data)))
    out_path = Path(args.out).resolve()
    out_path.write_text(html)
    print(f"wrote {out_path} ({len(data)} items) from {args.db}")
    webbrowser.open(out_path.as_uri())


if __name__ == "__main__":
    main()
