"""
Dashboard HTML builder
Generates the full single-page dark dashboard from the odds cache.
"""

import json


def build_dashboard_html(cache: dict) -> str:
    rows_json      = json.dumps(cache.get("rows", []))
    last_updated   = cache.get("last_updated", "Never")
    status         = cache.get("status", "—")
    is_refreshing  = cache.get("is_refreshing", False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>⚽ Odds Dashboard</title>
<style>
  :root {{
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2d3144;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --accent:   #6366f1;
    --green:    #22c55e;
    --red:      #ef4444;
    --yellow:   #eab308;
    --badge-bg: #1e293b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    min-height: 100vh;
  }}
  .header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
  }}
  .header h1 {{ font-size: 1.2rem; font-weight: 700; }}
  .header h1 span {{ color: var(--accent); }}
  .status-bar {{
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 0.8rem;
    color: var(--muted);
  }}
  .status-dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }}
  .status-dot.refreshing {{ background: var(--yellow); }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.4; }}
  }}
  .refresh-btn {{
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    cursor: pointer;
    font-size: 0.8rem;
    font-weight: 600;
    transition: opacity 0.2s;
  }}
  .refresh-btn:hover {{ opacity: 0.85; }}
  .controls {{
    padding: 16px 24px;
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
    border-bottom: 1px solid var(--border);
  }}
  .search-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 14px;
    border-radius: 8px;
    width: 260px;
    font-size: 0.85rem;
    outline: none;
  }}
  .search-box:focus {{ border-color: var(--accent); }}
  .filter-group {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .filter-btn {{
    background: var(--badge-bg);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 6px 12px;
    border-radius: 20px;
    cursor: pointer;
    font-size: 0.75rem;
    transition: all 0.15s;
  }}
  .filter-btn.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }}
  .stats {{ margin-left: auto; color: var(--muted); font-size: 0.8rem; }}
  .stats strong {{ color: var(--text); }}
  .table-wrap {{
    padding: 0 24px 40px;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 16px;
  }}
  thead th {{
    background: var(--surface);
    color: var(--muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 10px 14px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}
  thead th:hover {{ color: var(--text); }}
  thead th .sort-arrow {{ margin-left: 4px; opacity: 0.4; }}
  thead th.sorted .sort-arrow {{ opacity: 1; color: var(--accent); }}
  tbody tr {{
    border-bottom: 1px solid var(--border);
    transition: background 0.1s;
  }}
  tbody tr:hover {{ background: var(--surface); }}
  td {{
    padding: 10px 14px;
    white-space: nowrap;
  }}
  .league-badge {{
    display: inline-block;
    background: var(--badge-bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.7rem;
    color: var(--muted);
  }}
  .market-badge {{ font-size: 0.75rem; font-weight: 600; color: var(--accent); }}
  .sign-badge {{
    display: inline-block;
    background: rgba(99,102,241,0.15);
    color: var(--accent);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.75rem;
    font-weight: 700;
  }}
  .odd-val {{ font-weight: 700; font-size: 1rem; letter-spacing: -0.01em; }}
  .odd-best  {{ color: var(--green); }}
  .odd-worse {{ color: var(--muted); }}
  .diff-positive {{ color: var(--green); font-weight: 700; }}
  .diff-negative {{ color: var(--red); }}
  .diff-zero     {{ color: var(--muted); }}
  .no-data {{ color: var(--muted); font-size: 0.75rem; }}
  .empty {{
    text-align: center;
    padding: 80px 24px;
    color: var(--muted);
  }}
  .empty .icon {{ font-size: 3rem; margin-bottom: 12px; }}
  .spinner {{
    display: inline-block;
    width: 40px; height: 40px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body>
<div class="header">
  <h1>⚽ Odds <span>Dashboard</span></h1>
  <div class="status-bar">
    <div class="status-dot {'refreshing' if is_refreshing else ''}"></div>
    <span id="status-txt">{status}</span>
    <span>Updated: <strong id="updated-txt">{last_updated}</strong></span>
    <button class="refresh-btn" onclick="triggerRefresh()">↻ Refresh</button>
  </div>
</div>
<div class="controls">
  <input class="search-box" id="search" placeholder="Search match or league…" oninput="applyFilters()"/>
  <div class="filter-group" id="league-filters"></div>
  <div class="stats">Showing <strong id="count">0</strong> rows</div>
</div>
<div class="table-wrap">
  <table id="main-table">
    <thead>
      <tr>
        <th onclick="sortBy('league')">League <span class="sort-arrow">↕</span></th>
        <th onclick="sortBy('event')">Match <span class="sort-arrow">↕</span></th>
        <th onclick="sortBy('market')">Market <span class="sort-arrow">↕</span></th>
        <th onclick="sortBy('sign')">Selection <span class="sort-arrow">↕</span></th>
        <th onclick="sortBy('bet9ja')">Bet9ja <span class="sort-arrow">↕</span></th>
        <th onclick="sortBy('sportybet')">SportyBet <span class="sort-arrow">↕</span></th>
        <th onclick="sortBy('diff')">Diff <span class="sort-arrow">↕</span></th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div id="empty-state" class="empty" style="display:none">
    <div class="icon">{'<div class="spinner"></div>' if is_refreshing else '📭'}</div>
    <p>{'Fetching odds — this takes ~30s on first load…' if is_refreshing else 'No data yet. Click Refresh to start.'}</p>
  </div>
</div>
<script>
const RAW_ROWS = {rows_json};
let sortKey = 'diff', sortDir = -1, activeLeague = 'All', searchTerm = '';
const leagues = ['All', ...new Set(RAW_ROWS.map(r => r.league).filter(Boolean))].sort();
const filterEl = document.getElementById('league-filters');
leagues.forEach(l => {{
  const btn = document.createElement('button');
  btn.className = 'filter-btn' + (l === 'All' ? ' active' : '');
  btn.textContent = l;
  btn.onclick = () => {{
    activeLeague = l;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  }};
  filterEl.appendChild(btn);
}});
function sortBy(key) {{
  if (sortKey === key) sortDir *= -1;
  else {{ sortKey = key; sortDir = key === 'diff' ? -1 : 1; }}
  applyFilters();
}}
function applyFilters() {{
  searchTerm = document.getElementById('search').value.toLowerCase();
  let filtered = RAW_ROWS.filter(r => {{
    if (activeLeague !== 'All' && r.league !== activeLeague) return false;
    if (searchTerm && !r.event.toLowerCase().includes(searchTerm) && !r.league.toLowerCase().includes(searchTerm)) return false;
    return true;
  }});
  filtered.sort((a, b) => {{
    let av = a[sortKey], bv = b[sortKey];
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
    av = av ?? ''; bv = bv ?? '';
    return String(av).localeCompare(String(bv)) * sortDir;
  }});
  renderTable(filtered);
  document.getElementById('count').textContent = filtered.length;
}}
function oddCell(val, isBest) {{
  if (!val || val === '—') return '<td class="no-data">—</td>';
  return '<td><span class="odd-val ' + (isBest ? 'odd-best' : 'odd-worse') + '">' + val + '</span></td>';
}}
function renderTable(data) {{
  const tbody = document.getElementById('tbody');
  const empty = document.getElementById('empty-state');
  if (!data.length) {{ tbody.innerHTML = ''; empty.style.display = 'block'; return; }}
  empty.style.display = 'none';
  tbody.innerHTML = data.map(r => {{
    const b9f = parseFloat(r.bet9ja) || 0, sbf = parseFloat(r.sportybet) || 0;
    const b9Best = b9f > 0 && (sbf === 0 || b9f >= sbf);
    const sbBest = sbf > 0 && (b9f === 0 || sbf >= b9f);
    let diffHtml = '<td class="no-data">—</td>';
    if (r.diff !== null && r.diff !== undefined) {{
      const cls = r.diff > 0 ? 'diff-positive' : r.diff < 0 ? 'diff-negative' : 'diff-zero';
      diffHtml = '<td><span class="' + cls + '">' + (r.diff > 0 ? '+' : '') + r.diff.toFixed(3) + '</span></td>';
    }}
    return '<tr><td><span class="league-badge">' + r.league + '</span></td><td>' + r.event + '</td><td><span class="market-badge">' + r.market + '</span></td><td><span class="sign-badge">' + r.sign + '</span></td>' + oddCell(r.bet9ja, b9Best) + oddCell(r.sportybet, sbBest) + diffHtml + '</tr>';
  }}).join('');
}}
let countdown = {REFRESH_MINUTES * 60};
setInterval(() => {{ countdown--; if (countdown <= 0) location.reload(); }}, 1000);
async function triggerRefresh() {{ await fetch('/api/refresh'); setTimeout(() => location.reload(), 3000); }}
applyFilters();
</script>
</body>
</html>"""


REFRESH_MINUTES = 10
