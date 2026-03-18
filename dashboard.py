"""
Dashboard HTML builder - 5-bookmaker odds dashboard with:
  - Tab navigation: Odds Dashboard | Bet Comparison
  - Sortable, filterable odds table with 5 bookmakers + checkbox selection
  - Selection bar with "Generate Comparison" button for custom comparisons
  - Accumulator cards with 5 bookmaker boxes + responsive grid
  - Auto-refresh every 10 minutes
  - Dark theme throughout
"""


def build_dashboard_html(cache: dict) -> str:
    import json
    from datetime import datetime

    # Extract data from cache
    rows = cache.get("rows", [])
    last_updated = cache.get("last_updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    status = cache.get("status", "Live")

    # Convert rows to JSON for JavaScript
    rows_json = json.dumps(rows, ensure_ascii=False)

    # Extract unique leagues and markets
    leagues = sorted(set(row.get("league", "Unknown") for row in rows if row.get("league")))
    markets = sorted(set(row.get("market", "Unknown") for row in rows if row.get("market")))

    # Build league filter buttons
    league_buttons = "\n".join(
        f'<button class="filter-btn" data-league="{league}">{league}</button>'
        for league in leagues
    )

    # Build market filter buttons
    market_buttons = "\n".join(
        f'<button class="filter-btn" data-market="{market}">{market}</button>'
        for market in markets
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Odds Dashboard - 5 Bookmakers</title>
<style>
/* -- Reset & Base ---------------------------------- */
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}}

/* -- Header ---------------------------------------- */
.header{{background:#1a1d27;border-bottom:1px solid #2d3144;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
.header h1{{font-size:1.3rem;white-space:nowrap}} .header h1 span{{color:#6366f1}}
.header-right{{display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.status{{font-size:.78rem;color:#64748b;max-width:340px;text-overflow:ellipsis;overflow:hidden;white-space:nowrap}}
.btn{{padding:6px 14px;border-radius:6px;border:none;cursor:pointer;font-size:.8rem;font-weight:600;transition:background .15s}}
.btn-refresh{{background:#22c55e;color:#fff}} .btn-refresh:hover{{background:#16a34a}}
.btn-logout{{background:#334155;color:#94a3b8;text-decoration:none;display:inline-block}} .btn-logout:hover{{background:#475569;color:#e2e8f0}}

/* -- Tabs ------------------------------------------- */
.tabs{{display:flex;gap:0;background:#1a1d27;border-bottom:1px solid #2d3144;padding:0 24px}}
.tab-btn{{padding:12px 24px;font-size:.9rem;font-weight:600;color:#64748b;cursor:pointer;border:none;background:transparent;border-bottom:2px solid transparent;transition:all .15s}}
.tab-btn:hover{{color:#e2e8f0}} .tab-btn.active{{color:#6366f1;border-bottom-color:#6366f1}}

/* -- Tab Content ------------------------------------ */
.tab-content{{display:none;padding:20px 24px}} .tab-content.active{{display:block}}

/* -- Filters ---------------------------------------- */
.filters{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;align-items:center}}
.search-box{{padding:8px 12px;border-radius:8px;border:1px solid #2d3144;background:#1a1d27;color:#e2e8f0;font-size:.85rem;width:260px;outline:none}}
.search-box:focus{{border-color:#6366f1}}
.filter-btn{{padding:5px 12px;border-radius:6px;border:1px solid #2d3144;background:#1a1d27;color:#94a3b8;cursor:pointer;font-size:.78rem;font-weight:500;transition:all .15s}}
.filter-btn:hover{{border-color:#6366f1;color:#e2e8f0}}
.filter-btn.active{{background:#6366f1;color:#fff;border-color:#6366f1}}
.filter-group{{display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.filter-label{{font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.5px;font-weight:700;margin-right:4px}}

/* -- Selection Bar ---------------------------------- */
.selection-bar{{display:none;background:#1a1d27;border:2px solid #6366f1;border-radius:8px;padding:12px 16px;margin-bottom:16px;align-items:center;gap:16px;position:sticky;top:24px;z-index:50}}
.selection-bar.active{{display:flex}}
.selection-count{{font-weight:600;color:#6366f1;font-size:.9rem;min-width:120px}}
.compare-btn{{padding:6px 16px;background:#6366f1;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:.8rem;font-weight:600;transition:background .15s}}
.compare-btn:hover{{background:#4f46e5}}
.compare-btn:disabled{{background:#475569;cursor:not-allowed;opacity:.5}}

/* -- Table ------------------------------------------ */
.table-wrap{{overflow-x:auto;border-radius:10px;border:1px solid #2d3144}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
th{{background:#1a1d27;padding:10px 12px;text-align:left;font-weight:700;color:#94a3b8;cursor:pointer;white-space:nowrap;user-select:none;position:sticky;top:0;border-bottom:1px solid #2d3144}}
th:hover{{color:#e2e8f0}}
th .sort-arrow{{margin-left:4px;font-size:.65rem;opacity:.4}}
th.sorted .sort-arrow{{opacity:1;color:#6366f1}}
td{{padding:9px 12px;border-bottom:1px solid rgba(45,49,68,.4);white-space:nowrap}}
tr:hover td{{background:rgba(99,102,241,.05)}}
.checkbox-cell{{text-align:center;width:40px}}
.checkbox-cell input{{cursor:pointer;accent-color:#6366f1}}
.league-cell{{color:#64748b;font-size:.75rem}}
.datetime-cell{{color:#94a3b8;font-size:.75rem;white-space:nowrap}}
.event-cell{{font-weight:600;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
.market-cell{{color:#94a3b8}}
.sign-cell{{font-weight:700;color:#e2e8f0}}
.odds-cell{{font-variant-numeric:tabular-nums}}
.odds-cell.best{{background:rgba(34,197,94,.15);color:#22c55e;font-weight:700}}
.diff-pos{{color:#22c55e;font-weight:700}}
.diff-neg{{color:#ef4444;font-weight:700}}
.diff-zero{{color:#64748b}}
.missing{{color:#475569}}
.row-count{{font-size:.78rem;color:#64748b;margin-top:10px;text-align:right}}

/* -- Accumulator Cards ------------------------------ */
.acca-grid{{display:grid;grid-template-columns:1fr;gap:16px;max-width:900px;margin:0 auto}}
.acca-card{{background:#1a1d27;border:1px solid #2d3144;border-radius:12px;overflow:visible}}
.acca-header{{padding:14px 18px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2d3144}}
.acca-size{{font-weight:700;font-size:1.05rem}} .acca-size span{{color:#6366f1}}
.acca-body{{padding:14px 18px;overflow-x:auto}}
.acca-body table{{width:100%;min-width:600px;font-size:0.85em}}
.sel-list{{list-style:none;padding:0;margin:0 0 14px}}
.sel-item{{padding:4px 0;font-size:.8rem;color:#cbd5e1;display:flex;justify-content:space-between}}
.sel-sign{{color:#6366f1;font-weight:700;margin-left:8px}}
.bookmaker-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}}
.bm-box{{background:#0f1117;border-radius:8px;padding:12px;border:2px solid #2d3144;text-align:center;transition:all .2s}}
.bm-box.bet9ja{{border-color:#22c55e}} .bm-box.bet9ja.best{{box-shadow:0 0 12px rgba(34,197,94,.3)}}
.bm-box.sportybet{{border-color:#f59e0b}} .bm-box.sportybet.best{{box-shadow:0 0 12px rgba(245,158,11,.3)}}
.bm-box.msport{{border-color:#ef4444}}
.bm-box.yajuego{{border-color:#8b5cf6}} .bm-box.msport.best{{box-shadow:0 0 12px rgba(239,68,68,.3)}}
.bm-box.yajuego.best{{box-shadow:0 0 12px rgba(139,92,246,.3)}}
.bm-box.best{{font-weight:700;background:rgba(34,197,94,.08)}}
.bm-name{{font-weight:700;font-size:.75rem;text-transform:uppercase;margin-bottom:6px;opacity:.9}}
.bm-odds{{font-size:1.1rem;font-weight:700;font-variant-numeric:tabular-nums}}
.acca-loading{{text-align:center;padding:60px;color:#64748b;font-size:.9rem}}
.acca-empty{{text-align:center;padding:60px;color:#64748b}}

/* -- Responsive ------------------------------------- */
@media(max-width:1024px){{
  .acca-grid{{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}}
  .bookmaker-grid{{grid-template-columns:repeat(4,1fr)}}
}}
@media(max-width:768px){{
  .header{{padding:12px 16px}} .tab-content{{padding:16px}} .search-box{{width:100%}}
  .acca-grid{{grid-template-columns:1fr}} .bookmaker-grid{{grid-template-columns:repeat(2,1fr)}}
  .filters{{gap:6px}} .selection-bar{{flex-wrap:wrap;top:auto}}
}}
/* -- Settings Modal -------------------------------- */
.settings-btn{{background:none;border:none;color:#94a3b8;cursor:pointer;font-size:1.2rem;padding:6px 10px;border-radius:6px;transition:all .2s}}
.settings-btn:hover{{color:#e2e8f0;background:#2d3144}}
.modal-overlay{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.6);z-index:1000;justify-content:center;align-items:center}}
.modal-overlay.active{{display:flex}}
.modal{{background:#1e2130;border:1px solid #2d3144;border-radius:12px;padding:24px;width:400px;max-width:90vw}}
.modal h3{{margin:0 0 16px;color:#e2e8f0;font-size:1.1rem}}
.modal label{{display:block;color:#94a3b8;margin-bottom:6px;font-size:.85rem}}
.modal select{{width:100%;padding:8px 12px;border-radius:8px;border:1px solid #2d3144;background:#0f1117;color:#e2e8f0;font-size:.9rem;margin-bottom:16px}}
.modal-actions{{display:flex;gap:8px;justify-content:flex-end}}
.modal .btn-save{{padding:8px 20px;border-radius:8px;border:none;background:#6366f1;color:#fff;cursor:pointer;font-weight:600}}
.modal .btn-save:hover{{background:#5558e6}}
.modal .btn-cancel{{padding:8px 20px;border-radius:8px;border:1px solid #2d3144;background:transparent;color:#94a3b8;cursor:pointer}}
.modal .btn-cancel:hover{{color:#e2e8f0}}
</style>
</head>
<body>

<!-- -- Header ---------------------------------------- -->
<div class="header">
  <h1>&#9917; Odds <span>Dashboard</span></h1>
  <div class="header-right">
    <span class="status" id="status">{status}</span>
    <span class="status" id="updated">Updated: {last_updated}</span>
    <button class="btn btn-refresh" onclick="triggerRefresh()">&#8635; Refresh</button>
    <button class="settings-btn" onclick="openSettings()" title="Settings">&#9881;</button>
    <a class="btn btn-logout" href="/logout">Logout</a>
  </div>
</div>

<!-- -- Tabs ------------------------------------------- -->
<div class="tabs">
  <button class="tab-btn active" data-tab="odds">Odds Dashboard</button>
  <button class="tab-btn" data-tab="accumulators">Bet Comparison</button>
</div>

<!-- ============= TAB 1: ODDS DASHBOARD =============== -->
<div class="tab-content active" id="tab-odds">
  <!-- Filters -->
  <div class="filters">
    <input class="search-box" id="search" placeholder="Search event or team&hellip;" oninput="applyFilters()">
    <div class="filter-group" id="league-filters">
      <span class="filter-label">League</span>
      {league_buttons}
    </div>
    <div class="filter-group" id="market-filters">
      <span class="filter-label">Market</span>
      {market_buttons}
    </div>
  </div>

  <!-- Selection Bar -->
  <div class="selection-bar" id="selection-bar">
    <span class="selection-count" id="selection-count">0 selections</span>
    <button class="compare-btn" id="compare-btn" onclick="generateCustomComparison()">Quick Compare</button>
        <button class="compare-btn" id="live-check-btn" onclick="generateLiveComparison()" style="background:#f59e0b;margin-left:8px;">Live Check</button>
  </div>

  <!-- Table -->
  <div class="table-wrap">
    <table id="odds-table">
      <thead>
        <tr>
          <th class="checkbox-cell"><input type="checkbox" id="select-all" onchange="toggleSelectAll(this)"></th>
          <th data-col="league">League <span class="sort-arrow">&#9650;</span></th>
          <th data-col="start_time">Date/Time <span class="sort-arrow">&#9650;</span></th>
          <th data-col="event">Event <span class="sort-arrow">&#9650;</span></th>
          <th data-col="market">Market <span class="sort-arrow">&#9650;</span></th>
          <th data-col="sign">Sign <span class="sort-arrow">&#9650;</span></th>
          <th data-col="bet9ja">Bet9ja <span class="sort-arrow">&#9650;</span></th>
          <th data-col="sportybet">SportyBet <span class="sort-arrow">&#9650;</span></th>
          <th data-col="msport">MSport <span class="sort-arrow">&#9650;</span></th>
            <th data-col="yajuego">YaJuego <span class="sort-arrow">&#9650;</span></th>
          <th data-col="diff">Best Diff <span class="sort-arrow">&#9650;</span></th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <div class="row-count" id="row-count"></div>
</div>

<!-- ============= TAB 2: BET COMPARISON ============== -->
<div class="tab-content" id="tab-accumulators">
  <div id="bookmaker-select" style="display:flex;gap:16px;padding:12px 16px;background:#1a1d27;border-radius:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap;">
    <span style="color:#aaa;font-size:.85rem;font-weight:600;">Compare on:</span>
    <label style="color:#e2e8f0;font-size:.85rem;cursor:pointer;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="bm-check" value="bet9ja" checked> Bet9ja</label>
    <label style="color:#e2e8f0;font-size:.85rem;cursor:pointer;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="bm-check" value="sportybet" checked> SportyBet</label>
    <label style="color:#e2e8f0;font-size:.85rem;cursor:pointer;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="bm-check" value="msport" checked> MSport</label>
    <label style="color:#e2e8f0;font-size:.85rem;cursor:pointer;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="bm-check" value="yajuego" checked> YaJuego</label>
  </div>
  <div class="acca-loading" id="acca-loading" style="display:none">Generating comparison&hellip;</div>
  <div class="acca-grid" id="acca-grid" style="display:none"></div>
  <div class="acca-empty" id="acca-empty">
    <p>Select rows from the Odds Dashboard, choose bookmakers above, and click "Generate Comparison".</p>
  </div>
</div>

<!-- Settings Modal -->
<div class="modal-overlay" id="settings-modal">
  <div class="modal">
    <h3>&#9881; Settings</h3>
    <label for="scrape-days">Scrape Date Range (days)</label>
    <select id="scrape-days">
      <option value="1">1 day</option>
      <option value="2" selected>2 days (default)</option>
      <option value="3">3 days</option>
      <option value="4">4 days</option>
      <option value="5">5 days</option>
      <option value="7">7 days</option>
      <option value="10">10 days</option>
    </select>
    <p style="color:#64748b;font-size:.8rem;margin:0 0 16px">Controls how many days ahead the scrapers will fetch matches. A larger range means more matches but slower scrapes.</p>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeSettings()">Cancel</button>
      <button class="btn-save" onclick="saveSettings()">Save</button>
    </div>
  </div>
</div>

<script>
// ── Settings ─────────────────────────────────────────
function openSettings() {{
  fetch('/api/settings', {{ headers: {{ 'Authorization': 'Bearer ' + localStorage.getItem('token') }} }})
    .then(r => r.json())
    .then(data => {{
      document.getElementById('scrape-days').value = data.scrape_days || 2;
      document.getElementById('settings-modal').classList.add('active');
    }})
    .catch(() => document.getElementById('settings-modal').classList.add('active'));
}}
function closeSettings() {{
  document.getElementById('settings-modal').classList.remove('active');
}}
function saveSettings() {{
  const days = document.getElementById('scrape-days').value;
  fetch('/api/settings', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('token') }},
    body: JSON.stringify({{ scrape_days: parseInt(days) }})
  }})
  .then(r => r.json())
  .then(data => {{
    closeSettings();
    const statusEl = document.getElementById('scrape-status');
    if (statusEl) statusEl.textContent = 'Scrape range: ' + days + ' days';
    alert('Settings saved! Scrape range set to ' + days + ' days. Changes take effect on next refresh.');
  }})
  .catch(e => alert('Failed to save: ' + e.message));
}}
// Close modal on overlay click
document.addEventListener('DOMContentLoaded', function() {{
  const overlay = document.getElementById('settings-modal');
  if (overlay) overlay.addEventListener('click', function(e) {{
    if (e.target === overlay) closeSettings();
  }});
}});

/* -- Data -------------------------------------------- */
const RAW_ROWS = {rows_json};
let filteredRows = [...RAW_ROWS];
let sortCol = "diff", sortAsc = false;
let selectedIndices = new Set();
let activeLeagues = new Set();
let activeMarkets = new Set();

/* -- Bookmaker Config -------------------------------- */
const BOOKMAKERS = [
  {{key: 'bet9ja', name: 'Bet9ja', cls: 'bet9ja'}},
  {{key: 'sportybet', name: 'SportyBet', cls: 'sportybet'}},
  {{key: 'msport', name: 'MSport', cls: 'msport'}},
    {{key: 'yajuego', name: 'YaJuego', cls: 'yajuego'}},
];

/* -- Auth Helper ---- */
function getAuthHeaders() {{
  const token = localStorage.getItem('token');
  return {{'Authorization': 'Bearer ' + (token || '')}};
}}

/* -- Date/Time Formatter ----------------------------- */
function formatDateTime(st) {{
  if (!st) return '\u2014';
  try {{
    const d = new Date(st.replace(' ', 'T'));
    if (isNaN(d.getTime())) return st;
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${{dd}}/${{mm}} ${{hh}}:${{min}}`;
  }} catch(e) {{ return st; }}
}}

/* -- Tab Switching ----------------------------------- */
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    // loadAccumulators removed - comparison tab starts empty
  }});
}});

/* -- League & Market Filters ------------------------- */
(function buildFilters() {{
  const lf = document.getElementById('league-filters');
  lf.querySelectorAll('.filter-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const league = btn.getAttribute('data-league');
      btn.classList.toggle('active');
      if (btn.classList.contains('active')) {{
        activeLeagues.add(league);
      }} else {{
        activeLeagues.delete(league);
      }}
      applyFilters();
    }});
  }});

  const mf = document.getElementById('market-filters');
  mf.querySelectorAll('.filter-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const market = btn.getAttribute('data-market');
      btn.classList.toggle('active');
      if (btn.classList.contains('active')) {{
        activeMarkets.add(market);
      }} else {{
        activeMarkets.delete(market);
      }}
      applyFilters();
    }});
  }});
}})();

/* -- Filtering --------------------------------------- */
function applyFilters() {{
  const q = document.getElementById('search').value.toLowerCase();
  filteredRows = RAW_ROWS.filter(r => {{
    const matchLeague = activeLeagues.size === 0 || activeLeagues.has(r.league);
    const matchMarket = activeMarkets.size === 0 || activeMarkets.has(r.market);
    const matchSearch = q === '' || r.event.toLowerCase().includes(q) || r.league.toLowerCase().includes(q);
    return matchLeague && matchMarket && matchSearch;
  }});
  selectedIndices.clear();
  document.getElementById('select-all').checked = false;
  updateSelectionBar();
  doSort();
}}

/* -- Sorting ----------------------------------------- */
document.querySelectorAll('#odds-table th').forEach(th => {{
  if (th.hasAttribute('data-col')) {{
    th.addEventListener('click', () => {{
      const col = th.dataset.col;
      if (sortCol === col) sortAsc = !sortAsc;
      else {{ sortCol = col; sortAsc = true; }}
      document.querySelectorAll('#odds-table th').forEach(h => h.classList.remove('sorted'));
      th.classList.add('sorted');
      th.querySelector('.sort-arrow').textContent = sortAsc ? '\u25B2' : '\u25BC';
      doSort();
    }});
  }}
}});

function doSort() {{
  filteredRows.sort((a, b) => {{
    let va = a[sortCol], vb = b[sortCol];
    if (sortCol === 'diff') {{
      va = va ?? (sortAsc ? 9999 : -9999);
      vb = vb ?? (sortAsc ? 9999 : -9999);
      return sortAsc ? va - vb : vb - va;
    }}
    if (['bet9ja', 'sportybet', 'msport', 'yajuego'].includes(sortCol)) {{
      va = va === '-' ? null : parseFloat(va);
      vb = vb === '-' ? null : parseFloat(vb);
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      return sortAsc ? va - vb : vb - va;
    }}
    va = (va || '').toString().toLowerCase();
    vb = (vb || '').toString().toLowerCase();
    return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
  }});
  renderTable();
}}

/* -- Render Table ------------------------------------ */
function renderTable() {{
  const tbody = document.getElementById('tbody');
  let html = '';
  for (let idx = 0; idx < filteredRows.length; idx++) {{
    const r = filteredRows[idx];
    const odds = BOOKMAKERS.map(bm => {{
      const val = r[bm.key];
      return val && val !== '-' ? parseFloat(val) : null;
    }}).filter(v => v !== null);
    const maxOdds = odds.length > 0 ? Math.max(...odds) : 0;

    const diff = r.diff;
    let diffCls = 'diff-zero', diffTxt = '-';
    if (diff !== null && diff !== undefined) {{
      diffTxt = (diff > 0 ? '+' : '') + diff.toFixed(3);
      diffCls = diff > 0 ? 'diff-pos' : diff < 0 ? 'diff-neg' : 'diff-zero';
    }}

    let cellsHtml = BOOKMAKERS.map(bm => {{
      const val = r[bm.key] || '-';
      const numVal = val === '-' ? 0 : parseFloat(val);
      const isBest = numVal > 0 && numVal === maxOdds;
      return `<td class="odds-cell ${{isBest ? 'best' : ''}}">${{val}}</td>`;
    }}).join('');

    html += `<tr>
      <td class="checkbox-cell"><input type="checkbox" class="row-cb" data-idx="${{idx}}" onchange="updateSelection()"></td>
      <td class="league-cell">${{r.league}}</td>
            <td class="datetime-cell">${{formatDateTime(r.start_time)}}</td>
      <td class="event-cell">${{r.event}}</td>
      <td class="market-cell">${{r.market}}</td>
      <td class="sign-cell">${{r.sign}}</td>
      ${{cellsHtml}}
      <td class="${{diffCls}}">${{diffTxt}}</td>
    </tr>`;
  }}
  tbody.innerHTML = html;
  document.getElementById('row-count').textContent = `Showing ${{filteredRows.length}} of ${{RAW_ROWS.length}} rows`;
}}

/* -- Checkbox Selection ------------------------------ */
function toggleSelectAll(checkbox) {{
  document.querySelectorAll('.row-cb').forEach(cb => {{
    cb.checked = checkbox.checked;
  }});
  updateSelection();
}}

function updateSelection() {{
  selectedIndices.clear();
  document.querySelectorAll('.row-cb:checked').forEach(cb => {{
    selectedIndices.add(parseInt(cb.getAttribute('data-idx')));
  }});
  updateSelectionBar();
}}

function updateSelectionBar() {{
  const bar = document.getElementById('selection-bar');
  const count = selectedIndices.size;
  document.getElementById('selection-count').textContent = count + ' selection' + (count !== 1 ? 's' : '');
  if (count > 0) {{
    bar.classList.add('active');
  }} else {{
    bar.classList.remove('active');
  }}
}}

/* -- Custom Comparison ----------------------------------- */
  async function generateCustomComparison() {{
    if (selectedIndices.size === 0) {{
      alert('Please select at least one row');
      return;
    }}

    const selectedRows = Array.from(selectedIndices).map(idx => filteredRows[idx]);
    const bookmakers = Array.from(document.querySelectorAll('.bm-check:checked')).map(c => c.value);

    /* Show loading & switch to Bet Comparison tab */
    document.getElementById('acca-loading').style.display = '';
    document.getElementById('acca-empty').style.display = 'none';
    document.getElementById('acca-grid').style.display = 'none';
    document.querySelectorAll('.tab-btn')[1].click();

    try {{
      const res = await fetch('/api/custom-comparison', {{
        method: 'POST',
        headers: Object.assign({{'Content-Type': 'application/json'}}, getAuthHeaders()),
        body: JSON.stringify({{selections: selectedRows, stake: 100, bookmakers: bookmakers}})
      }});

      if (!res.ok) {{ const errData = await res.json().catch(() => ({{}})); throw new Error(res.status + ': ' + (errData.detail || 'API error')); }}
      const data = await res.json();

      renderCustomComparison(data);
    }} catch (e) {{
      console.error('Error:', e);
      document.getElementById('acca-loading').style.display = 'none';
      document.getElementById('acca-empty').style.display = '';
      if (e.message && e.message.startsWith('401')) {{ alert('Session expired. Please log in again.'); window.location.href = '/login'; }} else {{ alert('Failed to generate comparison: ' + (e.message || 'Unknown error')); }}
    }}
  }}

  async function generateLiveComparison() {{
        if (selectedIndices.size === 0) {{ alert('Please select at least one row'); return; }}
        const selectedRows = Array.from(selectedIndices).map(idx => filteredRows[idx]);
        const bookmakers = Array.from(document.querySelectorAll('.bm-check:checked')).map(c => c.value);
        document.getElementById('acca-loading').style.display = '';
        document.getElementById('acca-loading').textContent = 'Live checking betslips on bookmaker sites... (this may take 2-5 minutes)';
        document.getElementById('acca-empty').style.display = 'none';
        document.getElementById('acca-grid').style.display = 'none';
        document.querySelectorAll('.tab-btn')[1].click();
        try {{
            const res = await fetch('/api/live-comparison', {{
                method: 'POST',
                headers: Object.assign({{'Content-Type': 'application/json'}}, getAuthHeaders()),
                body: JSON.stringify({{selections: selectedRows, stake: 100, bookmakers: bookmakers}})
            }});
            if (!res.ok) {{ const errData = await res.json().catch(() => ({{}})); throw new Error(res.status + ': ' + (errData.detail || 'API error')); }}
            const data = await res.json();
            renderLiveComparison(data);
        }} catch (e) {{
            console.error('Live comparison error:', e);
            document.getElementById('acca-loading').style.display = 'none';
            document.getElementById('acca-empty').style.display = '';
            if (e.message && e.message.startsWith('401')) {{ alert('Session expired. Please log in again.'); window.location.href = '/login'; }}
            else {{ alert('Live check failed: ' + (e.message || 'Unknown error') + '. Try Quick Compare instead.'); }}
        }}
    }}

    function renderLiveComparison(data) {{
        const grid = document.getElementById('acca-grid');
        if (!grid) return;
        grid.innerHTML = '';
        document.getElementById('acca-loading').style.display = 'none';
        document.getElementById('acca-empty').style.display = 'none';
        grid.style.display = '';
        const results = data.results || data;
        const sels = data.selections || [];
        const stake = data.stake || 100;
        const acca = {{ size: sels.length, selections: sels, returns: {{}} }};
        const BOOKS = ['bet9ja','sportybet','msport','yajuego'];
        BOOKS.forEach(b => {{
            const r = results[b] || {{}};
            if (r.status === 'success' && r.potential_win) {{
                acca.returns[b] = {{ odds: r.total_odds || 0, base_win: r.potential_win || 0, bonus_percent: r.bonus_percent || 0, bonus_amount: 0, potential_win: r.potential_win || 0 }};
            }} else {{
                acca.returns[b] = {{ odds: 0, base_win: 0, bonus_percent: 0, bonus_amount: 0, potential_win: 0 }};
            }}
        }});
        const card = createAccaCard(acca, 0);
        grid.appendChild(card);
    }}

    function renderCustomComparison(data) {{
    const grid = document.getElementById('acca-grid');
    if (!grid) return;
    grid.innerHTML = '';
    document.getElementById('acca-loading').style.display = 'none';
    document.getElementById('acca-empty').style.display = 'none';
    grid.style.display = '';
    const src = data.results || data;
    const acca = {{
      size: data.size || 0,
      selections: data.selections || [],
      returns: {{
        bet9ja: src.bet9ja || {{}},
        sportybet: src.sportybet || {{}},
        msport: src.msport || {{}},
        yajuego: src.yajuego || {{}}
      }}
    }};
    const card = createAccaCard(acca, 0);
    grid.appendChild(card);
  }}

async function loadAccumulators() {{
  try {{
    const res = await fetch('/api/accumulators', {{headers: getAuthHeaders()}});
    const data = await res.json();
    const el = document.getElementById('acca-grid');
    if (!el) return;
    el.innerHTML = '';
    document.getElementById('acca-loading').style.display = 'none';
    document.getElementById('acca-empty').style.display = 'none';
    el.style.display = '';
    if (!data.accumulators || data.accumulators.length === 0) {{
      el.innerHTML = '<p style="color:#aaa;text-align:center;padding:2rem;">No accumulators yet.</p>';
      return;
    }}
    data.accumulators.forEach((acca, idx) => {{
      const card = createAccaCard(acca, idx);
      el.appendChild(card);
    }});
  }} catch(e) {{
    console.error('loadAccumulators error', e);
  }}
}}

function createAccaCard(acca, idx) {{
  const card = document.createElement('div');
  card.className = 'acca-card';
  card.style.cssText = 'margin-bottom:1.5rem;padding:1rem;border-radius:10px;background:#1a1a2e;border:1px solid #333;';

  const BOOKS = ['bet9ja','sportybet','msport','yajuego'];
  const COLORS = {{'bet9ja':'#22c55e','sportybet':'#f59e0b','msport':'#ef4444','yajuego':'#8b5cf6'}};
  const LABELS = {{'bet9ja':'BET9JA','sportybet':'SPORTYBET','msport':'MSPORT','yajuego':'YAJUEGO'}};

  const sels = acca.selections || [];
  const returns = acca.returns || {{}};
  const stake = 100;

  let html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.8rem;">';
  html += '<h3 style="margin:0;color:#fff;font-size:1.1rem;">Acca #' + (idx+1) + ' - ' + sels.length + ' selections</h3>';
  html += '<span style="color:#aaa;font-size:0.85rem;">Stake: \u20A6' + stake.toLocaleString() + '</span></div>';

  html += '<table style="width:100%;border-collapse:collapse;margin-bottom:1rem;font-size:0.8rem;">';
  html += '<thead><tr style="border-bottom:1px solid #444;">';
  html += '<th style="text-align:left;padding:6px 4px;color:#aaa;">Event</th>';
  html += '<th style="text-align:center;padding:6px 4px;color:#aaa;">Mkt</th>';
  html += '<th style="text-align:center;padding:6px 4px;color:#aaa;">Sign</th>';
  BOOKS.forEach(b => {{
    html += '<th style="text-align:center;padding:6px 4px;color:' + COLORS[b] + ';">' + LABELS[b] + '</th>';
  }});
  html += '</tr></thead><tbody>';

  sels.forEach(s => {{
    html += '<tr style="border-bottom:1px solid #2a2a3e;">';
    html += '<td style="padding:5px 4px;color:#ddd;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + (s.event||'') + '">' + (s.event||'-') + '</td>';
    html += '<td style="text-align:center;padding:5px 4px;color:#aaa;">' + (s.market||'-') + '</td>';
    html += '<td style="text-align:center;padding:5px 4px;color:#fff;font-weight:600;">' + (s.sign||'-') + '</td>';
    BOOKS.forEach(b => {{
      const val = s[b];
      const ok = val && val !== '-' && val !== '';
      html += '<td style="text-align:center;padding:5px 4px;color:' + (ok ? '#fff' : '#555') + ';">' + (ok ? parseFloat(val).toFixed(2) : '-') + '</td>';
    }});
    html += '</tr>';
  }});
  html += '</tbody></table>';

  html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0.8rem;">';

  let bestWin = 0; let bestBook = "";
  BOOKS.forEach(b => {{
    const r = returns[b];
    if (r && r.potential_win > bestWin) {{ bestWin = r.potential_win; bestBook = b; }}
  }});

  BOOKS.forEach(b => {{
    const r = returns[b];
    if (!r) return;
    const pw = r.potential_win || 0;
    const isBest = (b === bestBook && pw > 0);
    const bdr = isBest ? '2px solid ' + COLORS[b] : '1px solid #333';
    const glow = isBest ? 'box-shadow:0 0 12px ' + COLORS[b] + '40;' : '';

    html += '<div style="background:#16162a;border-radius:8px;padding:0.8rem;border:' + bdr + ';' + glow + '">';
    html += '<div style="color:' + COLORS[b] + ';font-weight:700;font-size:0.85rem;margin-bottom:0.5rem;">' + LABELS[b];
    if (isBest) html += ' <span style="font-size:0.7rem;background:' + COLORS[b] + '22;padding:2px 6px;border-radius:4px;">BEST</span>';
    html += '</div>';

    if (pw > 0) {{
      html += '<div style="color:#aaa;font-size:0.78rem;line-height:1.6;">';
      html += 'Combined Odds: <span style="color:#fff;">' + (r.odds||0).toFixed(2) + '</span><br>';
      html += 'Base Win: <span style="color:#fff;">\u20A6' + (r.base_win||0).toFixed(2) + '</span><br>';
      if (r.bonus_percent > 0) {{
        html += 'Bonus: <span style="color:' + COLORS[b] + ';">+' + r.bonus_percent + '% (\u20A6' + (r.bonus_amount||0).toFixed(2) + ')</span><br>';
      }} else {{
        html += 'Bonus: <span style="color:#555;">None</span><br>';
      }}
      html += '</div>';
      html += '<div style="margin-top:0.4rem;font-size:1.2rem;font-weight:700;color:#fff;">\u20A6' + pw.toFixed(2) + '</div>';
    }} else {{
      html += '<div style="color:#555;font-size:0.85rem;padding:0.5rem 0;">Missing odds</div>';
      html += '<div style="font-size:1.1rem;color:#555;">-</div>';
    }}
    html += '</div>';
  }});

  html += '</div>';
  card.innerHTML = html;
  return card;
}}

/* ----------------------------------------------------------- */function triggerRefresh() {{
  fetch('/api/refresh', {{method: 'POST', headers: getAuthHeaders()}}).then(r => {{
    if (r.status === 429) {{
      document.getElementById('status').textContent = 'Refresh already in progress...';
      startRefreshPolling();
      return;
    }}
    startRefreshPolling();
  }});
}}

let refreshPollTimer = null;
function startRefreshPolling() {{
  const statusEl = document.getElementById('status');
  const updatedEl = document.getElementById('updated');
  const startTime = Date.now();
  const estTotal = 360; // estimated seconds
  
  // Create progress bar if not exists
  let bar = document.getElementById('refresh-bar');
  if (!bar) {{
    bar = document.createElement('div');
    bar.id = 'refresh-bar';
    bar.style.cssText = 'position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,#6366f1,#22c55e);z-index:9999;transition:width 1s linear;width:0%';
    document.body.appendChild(bar);
  }}
  bar.style.width = '0%';
  bar.style.display = 'block';
  
  if (refreshPollTimer) clearInterval(refreshPollTimer);
  refreshPollTimer = setInterval(() => {{
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    const pct = Math.min(95, Math.round((elapsed / estTotal) * 100));
    bar.style.width = pct + '%';
    statusEl.textContent = 'Refreshing... ' + elapsed + 's / ~' + estTotal + 's (' + pct + '%)';
    
    fetch('/api/status', {{headers: getAuthHeaders()}})
      .then(r => r.json())
      .then(d => {{
        if (!d.is_refreshing && d.total_rows > 0) {{
          clearInterval(refreshPollTimer);
          bar.style.width = '100%';
          statusEl.textContent = 'Refresh complete! Reloading...';
          setTimeout(() => location.reload(), 1000);
        }}
      }}).catch(() => {{}});
  }}, 5000);
}}

/* -- Auto-start poll if currently refreshing -- */
if (document.getElementById('status').textContent.includes('Refreshing')) {{
  startRefreshPolling();
}}

/* -- Auto-Refresh ------------------------------------ */
setTimeout(() => location.reload(), 10 * 60 * 1000);

/* -- Initial Render ---------------------------------- */
doSort();
</script>
</body>
</html>"""
