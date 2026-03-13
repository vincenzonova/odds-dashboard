"""
Dashboard HTML builder - single-file HTML with:
  - Tab navigation: Odds Dashboard | Bet Comparison
  - Sortable, filterable odds table with search + league/market filters
  - Accumulator cards with side-by-side Bet9ja vs SportyBet breakdown
  - Logout button in header
  - Auto-refresh every 10 minutes
  - Dark theme throughout
"""


def build_dashboard_html(cache: dict) -> str:
    import json
    rows_json = json.dumps(cache.get("rows", []))
    last_updated = cache.get("last_updated", "&mdash;")
    status = cache.get("status", "Loading&hellip;")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Odds Dashboard</title>
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

/* -- Table ------------------------------------------ */
.table-wrap{{overflow-x:auto;border-radius:10px;border:1px solid #2d3144}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
th{{background:#1a1d27;padding:10px 12px;text-align:left;font-weight:700;color:#94a3b8;cursor:pointer;white-space:nowrap;user-select:none;position:sticky;top:0;border-bottom:1px solid #2d3144}}
th:hover{{color:#e2e8f0}}
th .sort-arrow{{margin-left:4px;font-size:.65rem;opacity:.4}}
th.sorted .sort-arrow{{opacity:1;color:#6366f1}}
td{{padding:9px 12px;border-bottom:1px solid rgba(45,49,68,.4);white-space:nowrap}}
tr:hover td{{background:rgba(99,102,241,.05)}}
.league-cell{{color:#64748b;font-size:.75rem}}
.event-cell{{font-weight:600;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
.market-cell{{color:#94a3b8}}
.sign-cell{{font-weight:700;color:#e2e8f0}}
.odds-cell{{font-variant-numeric:tabular-nums}}
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
.bookmaker-compare{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.bm-box{{background:#0f1117;border-radius:8px;padding:12px;border:1px solid #2d3144}}
.bm-name{{font-weight:700;font-size:.82rem;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}}
.bm-b9 .bm-name{{color:#22c55e}} .bm-sb .bm-name{{color:#f59e0b}}
.bm-source{{font-size:.65rem;color:#64748b;font-weight:400;padding:2px 6px;background:#1a1d27;border-radius:4px;border:1px solid #2d3144}}
.bm-row{{display:flex;justify-content:space-between;font-size:.78rem;padding:2px 0}}
.bm-label{{color:#64748b}} .bm-val{{font-weight:600;font-variant-numeric:tabular-nums}}
.bm-total{{border-top:1px solid #2d3144;margin-top:6px;padding-top:6px}}
.bm-total .bm-val{{font-size:.95rem;color:#e2e8f0}}
.acca-loading{{text-align:center;padding:60px;color:#64748b;font-size:.9rem}}
.acca-empty{{text-align:center;padding:60px;color:#64748b}}
.naira{{font-family:'Inter',system-ui,sans-serif}}
.best-val{{color:#22c55e !important}}

/* -- Responsive ------------------------------------- */
@media(max-width:768px){{
  .header{{padding:12px 16px}} .tab-content{{padding:16px}} .search-box{{width:100%}}
  .acca-grid{{grid-template-columns:1fr}} .bookmaker-compare{{grid-template-columns:1fr}}
  .filters{{gap:6px}}
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

<!-- ============== TAB 1: ODDS DASHBOARD =============== -->
<div class="tab-content active" id="tab-odds">
  <!-- Filters -->
  <div class="filters">
    <input class="search-box" id="search" placeholder="Search event or team&hellip;" oninput="applyFilters()">
    <div class="filter-group" id="league-filters">
      <span class="filter-label">League</span>
    </div>
    <div class="filter-group" id="market-filters">
      <span class="filter-label">Market</span>
    </div>
  </div>

  <!-- Table -->
  <div class="table-wrap">
    <table id="odds-table">
      <thead>
        <tr>
          <th data-col="league">League <span class="sort-arrow">&#9650;</span></th>
          <th data-col="event">Event <span class="sort-arrow">&#9650;</span></th>
          <th data-col="market">Market <span class="sort-arrow">&#9650;</span></th>
          <th data-col="sign">Sign <span class="sort-arrow">&#9650;</span></th>
          <th data-col="bet9ja">Bet9ja <span class="sort-arrow">&#9650;</span></th>
          <th data-col="sportybet">SportyBet <span class="sort-arrow">&#9650;</span></th>
          <th data-col="diff">Diff <span class="sort-arrow">&#9650;</span></th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <div class="row-count" id="row-count"></div>
</div>

<!-- ============== TAB 2: BET COMPARISON =============== -->
<div class="tab-content" id="tab-accumulators">
  <div class="acca-loading" id="acca-loading">Loading accumulators&hellip;</div>
  
  <div style="text-align:right;margin:10px 0"><button onclick="regenerateAccas()" style="background:#6366f1;color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:.9rem" id="regen-btn">&#x1F504; Regenerate</button></div>
  <div class="acca-grid" id="acca-grid" style="display:none"></div>
  <div class="acca-empty" id="acca-empty" style="display:none">
    <p>No accumulators available yet. Need at least 3 matched events with 1X2 odds between 1.20-1.80 from both bookmakers.</p>
  </div>
</div>

<script>
/* -- Data -------------------------------------------- */
const RAW_ROWS = {rows_json};
let filteredRows = [...RAW_ROWS];
let sortCol = "diff", sortAsc = false;
let activeLeague = null, activeMarket = null;

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
  const leagues = [...new Set(RAW_ROWS.map(r => r.league))].sort();
  const markets = [...new Set(RAW_ROWS.map(r => r.market))].sort();

  const lf = document.getElementById('league-filters');
  const allL = document.createElement('button');
  allL.className = 'filter-btn active'; allL.textContent = 'All';
  allL.onclick = () => {{ activeLeague = null; setActiveFilter(lf, allL); applyFilters(); }};
  lf.appendChild(allL);
  leagues.forEach(lg => {{
    const b = document.createElement('button');
    b.className = 'filter-btn'; b.textContent = lg;
    b.onclick = () => {{ activeLeague = lg; setActiveFilter(lf, b); applyFilters(); }};
    lf.appendChild(b);
  }});

  const mf = document.getElementById('market-filters');
  const allM = document.createElement('button');
  allM.className = 'filter-btn active'; allM.textContent = 'All';
  allM.onclick = () => {{ activeMarket = null; setActiveFilter(mf, allM); applyFilters(); }};
  mf.appendChild(allM);
  markets.forEach(mk => {{
    const b = document.createElement('button');
    b.className = 'filter-btn'; b.textContent = mk;
    b.onclick = () => {{ activeMarket = mk; setActiveFilter(mf, b); applyFilters(); }};
    mf.appendChild(b);
  }});
}})();

function setActiveFilter(container, active) {{
  container.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  active.classList.add('active');
}}

/* -- Filtering --------------------------------------- */
function applyFilters() {{
  const q = document.getElementById('search').value.toLowerCase();
  filteredRows = RAW_ROWS.filter(r => {{
    if (activeLeague && r.league !== activeLeague) return false;
    if (activeMarket && r.market !== activeMarket) return false;
    if (q && !r.event.toLowerCase().includes(q) && !r.league.toLowerCase().includes(q)) return false;
    return true;
  }});
  doSort();
}}

/* -- Sorting ----------------------------------------- */
document.querySelectorAll('#odds-table th').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = true; }}
    document.querySelectorAll('#odds-table th').forEach(h => h.classList.remove('sorted'));
    th.classList.add('sorted');
    th.querySelector('.sort-arrow').textContent = sortAsc ? '\u25B2' : '\u25BC';
    doSort();
  }});
}});

function doSort() {{
  filteredRows.sort((a, b) => {{
    let va = a[sortCol], vb = b[sortCol];
    if (sortCol === 'diff') {{
      va = va ?? (sortAsc ? 9999 : -9999);
      vb = vb ?? (sortAsc ? 9999 : -9999);
      return sortAsc ? va - vb : vb - va;
    }}
    if (sortCol === 'bet9ja' || sortCol === 'sportybet') {{
      va = va === '\u2014' ? null : parseFloat(va);
      vb = vb === '\u2014' ? null : parseFloat(vb);
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
  for (const r of filteredRows) {{
    const diff = r.diff;
    let diffCls = 'diff-zero', diffTxt = '\u2014';
    if (diff !== null && diff !== undefined) {{
      diffTxt = (diff > 0 ? '+' : '') + diff.toFixed(3);
      diffCls = diff > 0 ? 'diff-pos' : diff < 0 ? 'diff-neg' : 'diff-zero';
    }}
    const b9Cls = r.bet9ja === '\u2014' ? 'missing' : 'odds-cell';
    const sbCls = r.sportybet === '\u2014' ? 'missing' : 'odds-cell';
    html += `<tr>
      <td class="league-cell">${{r.league}}</td>
      <td class="event-cell">${{r.event}}</td>
      <td class="market-cell">${{r.market}}</td>
      <td class="sign-cell">${{r.sign}}</td>
      <td class="${{b9Cls}}">${{r.bet9ja}}</td>
      <td class="${{sbCls}}">${{r.sportybet}}</td>
      <td class="${{diffCls}}">${{diffTxt}}</td>
    </tr>`;
  }}
  tbody.innerHTML = html;
  document.getElementById('row-count').textContent = `Showing ${{filteredRows.length}} of ${{RAW_ROWS.length}} rows`;
}}

/* -- Accumulators ------------------------------------ */
let accaLoaded = false;
async 
      function regenerateAccas() {
        const btn = document.getElementById('regen-btn');
        btn.disabled = true;
        btn.textContent = 'Regenerating...';
        fetch('/api/regenerate')
          .then(r => r.json())
          .then(data => {
            btn.disabled = false;
            btn.innerHTML = '&#x1F504; Regenerate';
            loadAccumulators();
          })
          .catch(err => {
            btn.disabled = false;
            btn.innerHTML = '&#x1F504; Regenerate';
            console.error('Regenerate failed:', err);
          });
      }
      function loadAccumulators() {{
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
      const b9 = acca.bet9ja;
      const sb = acca.sportybet;
      const bestOdds = b9.odds >= sb.odds ? 'b9' : 'sb';
      const bestTotal = b9.potential_win >= sb.potential_win ? 'b9' : 'sb';

      let selHtml = '';
      acca.selections.forEach(s => {{
                const b9O = s.bet9ja ? parseFloat(s.bet9ja).toFixed(2) : '';
                const sbO = s.sportybet ? parseFloat(s.sportybet).toFixed(2) : '';
                const oddsStr = b9O ? ' <span style="color:#64748b;font-size:.72rem">(B9:' + b9O + ' / SB:' + sbO + ')</span>' : '';
                selHtml += '<li class="sel-item"><span>' + s.event + oddsStr + '</span><span class="sel-sign">' + s.sign + '</span></li>';
            }});

      grid.innerHTML += `
        <div class="acca-card">
          <div class="acca-header">
            <span class="acca-size">Acca <span>#${{idx+1}}</span> &mdash; ${{acca.size}} selections</span>
          </div>
          <div class="acca-body">
            <ul class="sel-list">${{selHtml}}</ul>
            <div class="bookmaker-compare">
              <div class="bm-box bm-b9">
                <div class="bm-name"><span>Bet9ja</span><span class="bm-source">${b9.source === 'betslip' ? '\u2713 Real' : b9.source === 'calculated' ? '\u2713 Calculated' : '\u2248 Est.'}}</span></div>
                <div class="bm-row"><span class="bm-label">Combined Odds</span><span class="bm-val ${{bestOdds==='b9'?'best-val':''}}">${{b9.odds.toFixed(2)}}</span></div>
                <div class="bm-row"><span class="bm-label">Base Win (<span class="naira">&#8358;</span>100)</span><span class="bm-val"><span class="naira">&#8358;</span>${{fmtN(b9.base_win)}}</span></div>
                <div class="bm-row"><span class="bm-label">Bonus</span><span class="bm-val">${{b9.bonus_percent}}% (<span class="naira">&#8358;</span>${{fmtN(b9.bonus_amount)}})</span></div>
                <div class="bm-row bm-total"><span class="bm-label">Total Win</span><span class="bm-val ${{bestTotal==='b9'?'best-val':''}}" style="font-size:.95rem"><span class="naira">&#8358;</span>${{fmtN(b9.potential_win)}}</span></div>
              </div>
              <div class="bm-box bm-sb">
                <div class="bm-name"><span>SportyBet</span><span class="bm-source">${{sb.source === 'betslip' ? '\u2713 Real' : '\u2248 Est.'}}</span></div>
                <div class="bm-row"><span class="bm-label">Combined Odds</span><span class="bm-val ${{bestOdds==='sb'?'best-val':''}}">${{sb.odds.toFixed(2)}}</span></div>
                <div class="bm-row"><span class="bm-label">Base Win (<span class="naira">&#8358;</span>100)</span><span class="bm-val"><span class="naira">&#8358;</span>${{fmtN(sb.base_win)}}</span></div>
                <div class="bm-row"><span class="bm-label">Bonus</span><span class="bm-val">${{sb.bonus_percent}}% (<span class="naira">&#8358;</span>${{fmtN(sb.bonus_amount)}})</span></div>
                <div class="bm-row bm-total"><span class="bm-label">Total Win</span><span class="bm-val ${{bestTotal==='sb'?'best-val':''}}" style="font-size:.95rem"><span class="naira">&#8358;</span>${{fmtN(sb.potential_win)}}</span></div>
              </div>
            </div>
          </div>
        </div>`;
    }});
    accaLoaded = true;
  }} catch (e) {{
    const el = document.getElementById('acca-loading');
    el.textContent = 'Failed to load accumulators. Try refreshing.';
    el.style.display = 'block';
  }}
}}

function fmtN(n) {{ return n.toLocaleString('en-NG', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}

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
