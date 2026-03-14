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
.acca-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:16px}}
.acca-card{{background:#1a1d27;border:1px solid #2d3144;border-radius:12px;overflow:hidden}}
.acca-header{{padding:14px 18px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2d3144}}
.acca-size{{font-weight:700;font-size:1.05rem}} .acca-size span{{color:#6366f1}}
.acca-body{{padding:14px 18px}}
.sel-list{{list-style:none;padding:0;margin:0 0 14px}}
.sel-item{{padding:4px 0;font-size:.8rem;color:#cbd5e1;display:flex;justify-content:space-between}}
.sel-sign{{color:#6366f1;font-weight:700;margin-left:8px}}
.bookmaker-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:10px;margin-top:12px}}
.bm-box{{background:#0f1117;border-radius:8px;padding:12px;border:2px solid #2d3144;text-align:center;transition:all .2s}}
.bm-box.bet9ja{{border-color:#22c55e}} .bm-box.bet9ja.best{{box-shadow:0 0 12px rgba(34,197,94,.3)}}
.bm-box.sportybet{{border-color:#f59e0b}} .bm-box.sportybet.best{{box-shadow:0 0 12px rgba(245,158,11,.3)}}
.bm-box.betking{{border-color:#3b82f6}} .bm-box.betking.best{{box-shadow:0 0 12px rgba(59,130,246,.3)}}
.bm-box.msport{{border-color:#ef4444}} .bm-box.msport.best{{box-shadow:0 0 12px rgba(239,68,68,.3)}}
.bm-box.betano{{border-color:#8b5cf6}} .bm-box.betano.best{{box-shadow:0 0 12px rgba(139,92,246,.3)}}
.bm-box.best{{font-weight:700;background:rgba(34,197,94,.08)}}
.bm-name{{font-weight:700;font-size:.75rem;text-transform:uppercase;margin-bottom:6px;opacity:.9}}
.bm-odds{{font-size:1.1rem;font-weight:700;font-variant-numeric:tabular-nums}}
.acca-loading{{text-align:center;padding:60px;color:#64748b;font-size:.9rem}}
.acca-empty{{text-align:center;padding:60px;color:#64748b}}

/* -- Responsive ------------------------------------- */
@media(max-width:1024px){{
  .acca-grid{{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}}
  .bookmaker-grid{{grid-template-columns:repeat(2,1fr)}}
}}
@media(max-width:768px){{
  .header{{padding:12px 16px}} .tab-content{{padding:16px}} .search-box{{width:100%}}
  .acca-grid{{grid-template-columns:1fr}} .bookmaker-grid{{grid-template-columns:repeat(2,1fr)}}
  .filters{{gap:6px}} .selection-bar{{flex-wrap:wrap;top:auto}}
}}
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
    <button class="compare-btn" id="compare-btn" onclick="generateCustomComparison()">Generate Comparison</button>
  </div>

  <!-- Table -->
  <div class="table-wrap">
    <table id="odds-table">
      <thead>
        <tr>
          <th class="checkbox-cell"><input type="checkbox" id="select-all" onchange="toggleSelectAll(this)"></th>
          <th data-col="league">League <span class="sort-arrow">&#9650;</span></th>
          <th data-col="event">Event <span class="sort-arrow">&#9650;</span></th>
          <th data-col="market">Market <span class="sort-arrow">&#9650;</span></th>
          <th data-col="sign">Sign <span class="sort-arrow">&#9650;</span></th>
          <th data-col="bet9ja">Bet9ja <span class="sort-arrow">&#9650;</span></th>
          <th data-col="sportybet">SportyBet <span class="sort-arrow">&#9650;</span></th>
          <th data-col="betking">BetKing <span class="sort-arrow">&#9650;</span></th>
          <th data-col="msport">MSport <span class="sort-arrow">&#9650;</span></th>
          <th data-col="betano">Betano <span class="sort-arrow">&#9650;</span></th>
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
  <div class="acca-loading" id="acca-loading">Loading accumulators&hellip;</div>
  <div class="acca-grid" id="acca-grid" style="display:none"></div>
  <div class="acca-empty" id="acca-empty" style="display:none">
    <p>No accumulators available yet. Select rows from the Odds Dashboard and click "Generate Comparison".</p>
  </div>
</div>

<script>
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
  {{key: 'betking', name: 'BetKing', cls: 'betking'}},
  {{key: 'msport', name: 'MSport', cls: 'msport'}},
  {{key: 'betano', name: 'Betano', cls: 'betano'}}
];

/* -- Tab Switching ----------------------------------- */
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'accumulators') loadAccumulators();
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
    if (['bet9ja', 'sportybet', 'betking', 'msport', 'betano'].includes(sortCol)) {{
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

/* -- Custom Comparison ------------------------------- */
async function generateCustomComparison() {{
  if (selectedIndices.size === 0) {{
    alert('Please select at least one row');
    return;
  }}

  const selectedRows = Array.from(selectedIndices).map(idx => filteredRows[idx]);

  try {{
    const res = await fetch('/api/custom-comparison', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{rows: selectedRows}})
    }});

    if (!res.ok) throw new Error('API error');
    const data = await res.json();

    renderCustomComparison(data);
    document.querySelectorAll('.tab-btn')[1].click();
  }} catch (e) {{
    console.error('Error:', e);
    alert('Failed to generate comparison');
  }}
}}

function renderCustomComparison(data) {{
  const grid = document.getElementById('acca-grid');
  grid.innerHTML = '';
  grid.style.display = 'grid';
  document.getElementById('acca-loading').style.display = 'none';
  document.getElementById('acca-empty').style.display = 'none';

  if (!data.comparisons || data.comparisons.length === 0) {{
    document.getElementById('acca-empty').style.display = 'block';
    grid.style.display = 'none';
    return;
  }}

  data.comparisons.forEach(comp => {{
    const card = createAccaCard(comp);
    grid.appendChild(card);
  }});
}}

/* -- Accumulators ------------------------------------ */
let accaLoaded = false;
async function loadAccumulators() {{
  if (accaLoaded) return;
  try {{
    const res = await fetch('/api/accumulators');
    if (!res.ok) throw new Error('API error');
    const data = await res.json();
    document.getElementById('acca-loading').style.display = 'none';

    if (!data.accumulators || data.accumulators.length === 0) {{
      document.getElementById('acca-empty').style.display = 'block';
      accaLoaded = true;
      return;
    }}

    const grid = document.getElementById('acca-grid');
    grid.style.display = 'grid';
    grid.innerHTML = '';

    data.accumulators.forEach((acca, idx) => {{
      const comp = {{
        title: `Acca #${{idx+1}} - ${{acca.size}} selections`,
        bet9ja: acca.bet9ja ? acca.bet9ja.potential_win : 0,
        sportybet: acca.sportybet ? acca.sportybet.potential_win : 0,
        betking: acca.betking ? acca.betking.potential_win : 0,
        msport: acca.msport ? acca.msport.potential_win : 0,
        betano: acca.betano ? acca.betano.potential_win : 0
      }};
      const card = createAccaCard(comp);
      grid.appendChild(card);
    }});
    accaLoaded = true;
  }} catch (e) {{
    const el = document.getElementById('acca-loading');
    el.textContent = 'Failed to load accumulators. Try refreshing.';
  }}
}}

function createAccaCard(comp) {{
  const card = document.createElement('div');
  card.className = 'acca-card';

  const odds = BOOKMAKERS.map(bm => comp[bm.key] || 0);
  const maxOdds = Math.max(...odds);

  let html = `<div class="acca-header"><span class="acca-size">${{comp.title || 'Accumulator'}}</span></div>`;
  html += '<div class="bookmaker-grid">';

  BOOKMAKERS.forEach((bm, idx) => {{
    const val = comp[bm.key] || 0;
    const isBest = val === maxOdds && maxOdds > 0;
    html += `
      <div class="bm-box ${{bm.cls}} ${{isBest ? 'best' : ''}}">
        <div class="bm-name">${{bm.name}}</div>
        <div class="bm-odds">${{val ? val.toFixed(2) : '-'}}</div>
      </div>
    `;
  }});

  html += '</div>';
  card.innerHTML = html;
  return card;
}}

/* -- Refresh ----------------------------------------- */
function triggerRefresh() {{
  fetch('/api/refresh').then(() => {{
    document.getElementById('status').textContent = 'Refreshing\u2026';
    setTimeout(() => location.reload(), 15000);
  }});
}}

/* -- Auto-Refresh ------------------------------------ */
setTimeout(() => location.reload(), 10 * 60 * 1000);

/* -- Initial Render ---------------------------------- */
doSort();
</script>
</body>
</html>"""
