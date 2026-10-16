/* BMR-Com Vol Desk — renders data/web/<T>_desk.json (built daily by analytics/build_desk.py). */
(function () {
  var D = null, T = 'CT', charts = {}, mapIdx = 0, ivRange = 'long';
  var $ = function (id) { return document.getElementById(id); };
  var md = function (t) { return String(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); };
  var f1 = function (v, d) { return v == null || isNaN(v) ? '–' : (+v).toFixed(d == null ? 1 : d); };
  var sg = function (v, d) { return v == null || isNaN(v) ? '–' : (v > 0 ? '+' : '') + (+v).toFixed(d == null ? 1 : d); };
  var kf = function (v) { return v == null ? '–' : Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : Math.round(v).toLocaleString(); };
  var col = function (v, inv) { if (v == null || isNaN(v) || Math.abs(v) < 1e-9) return 'var(--dk-mut)'; return (inv ? v < 0 : v > 0) ? 'var(--dk-up)' : 'var(--dk-dn)'; };
  var C = { call: '#4f8ef7', put: '#e05d5d', atm: '#f0b429', rv: '#8b949e', wk: '#6e7681', up: '#3fb950', dn: '#f85149', grid: 'rgba(240,246,252,.07)', txt: '#8b949e' };
  function ord(n) { n = Math.round(n); var s = (n % 100 >= 11 && n % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th'; return n + s; }
  function kill(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }
  function base(extra) {
    var o = { responsive: true, maintainAspectRatio: false, animation: { duration: 200 }, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { labels: { color: C.txt, boxWidth: 10, font: { size: 11 } } }, tooltip: { backgroundColor: '#1c2128', borderColor: '#30363d', borderWidth: 1, titleColor: '#e6edf3', bodyColor: '#c9d1d9' } },
      scales: { x: { ticks: { color: C.txt, font: { size: 10 } }, grid: { color: C.grid } }, y: { ticks: { color: C.txt, font: { size: 10 } }, grid: { color: C.grid } } } };
    return Object.assign(o, extra || {});
  }
  // vertical marker lines (futures, walls) on a linear x axis
  var vlines = { id: 'vlines', afterDatasetsDraw: function (ch, a, o) {
    var L = (o && o.lines) || []; var x = ch.scales.x, y = ch.scales.y; if (!x || !y) return; var c = ch.ctx;
    var used = []; L.forEach(function (l) { if (l.v == null) return; var px = x.getPixelForValue(l.v); if (px < x.left || px > x.right) return;
      c.save(); c.strokeStyle = l.c; c.lineWidth = l.w || 1.5; c.setLineDash(l.dash || []); c.beginPath(); c.moveTo(px, y.top); c.lineTo(px, y.bottom); c.stroke();
      var row = 0; while (used.some(function (u) { return u.r === row && Math.abs(u.x - px) < 52; })) row++; used.push({ x: px, r: row });
      c.fillStyle = l.c; c.font = '600 10px system-ui'; c.textAlign = 'center'; c.fillText(l.t, px, y.top + 10 + row * 12); c.restore(); }); } };

  function kpi(lbl, val, sub, tone) { return '<div class="dk-k' + (tone ? ' ' + tone : '') + '"><span>' + lbl + '</span><b>' + val + '</b><small>' + (sub || '') + '</small></div>'; }
  function gauge(p) { if (p == null) return ''; return '<div class="dk-g"><i style="left:' + Math.max(0, Math.min(100, p)) + '%"></i></div>'; }

  function render() {
    var B = D, el = $('desk-body'); if (!B) return;
    var leanTone = /bull/.test(B.lean) ? 'up' : /bear/.test(B.lean) ? 'dn' : 'neu';
    var volTone = B.vol_view === 'rich' ? 'dn' : B.vol_view === 'cheap' ? 'up' : 'neu';
    var em = B.em || {};
    var h = '<div class="dk-head"><div><div class="dk-title">' + B.label + ' options · ' + B.front_label + '</div><div class="dk-sub">ICE settlement ' + B.date + ' · futures ' + f1(B.F, 2) + ' ' + B.unit + ' · ' + B.dte + ' days to option expiry' +
      (B.skipped && B.skipped.length ? ' · <span title="Short traded-only report — open interest incomplete">skipped incomplete report ' + B.skipped.join(', ') + '</span>' : '') + '</div></div>' +
      '<div class="dk-badges"><span class="dk-badge ' + leanTone + '">Options read: ' + B.lean + '</span><span class="dk-badge ' + volTone + '">Vol ' + B.vol_view + '</span></div></div>';
    h += '<div class="dk-kpis">' +
      kpi('ATM implied vol', f1(B.atm) + '%', '<span style="color:' + col(B.dIV1) + '">' + sg(B.dIV1) + '</span> d/d · <span style="color:' + col(B.dIV5) + '">' + sg(B.dIV5) + '</span> w/w') +
      kpi('IV percentile', B.pct1y == null ? '–' : ord(B.pct1y), (B.pct_lbl || '') + gauge(B.pct1y)) +
      kpi('Realized vol (20d)', f1(B.rv20) + '%', 'IV premium <b style="color:' + col(B.vrp, true) + '">' + sg(B.vrp) + '</b> pts · 60d ' + f1(B.rv60) + '%', B.vrp >= 5 ? 'dn' : B.vrp <= -2 ? 'up' : '') +
      kpi('25Δ risk reversal', sg(B.rr25) + ' vol', (B.rr25 > 0 ? 'calls over puts' : 'puts over calls') + ' · <span style="color:' + col(B.dRR5) + '">' + sg(B.dRR5) + '</span> w/w', B.rr25 > 1 ? 'up' : B.rr25 < -1 ? 'dn' : '') +
      kpi('Put/call open interest', f1(B.pc_oi, 2), '20-report avg ' + f1(B.pc_oi_avg, 2) + ' · P/C volume (wk) ' + f1(B.pc_vol5, 2), B.pc_oi > B.pc_oi_avg * 1.08 ? 'dn' : B.pc_oi < B.pc_oi_avg * 0.92 ? 'up' : '') +
      kpi('Expected move (1σ)', '±' + f1(em.week, 2) + '¢', 'this week · ±' + f1(em.expiry, 2) + '¢ to expiry (' + f1(B.F - em.expiry, 1) + '–' + f1(B.F + em.expiry, 1) + ')') +
      kpi('Futures', f1(B.F, 2), '<span style="color:' + col(B.r1) + '">' + sg(B.r1 * 100) + '%</span> d/d · <span style="color:' + col(B.r5) + '">' + sg(B.r5 * 100) + '%</span> week') +
      kpi('Open interest', kf(B.cOI) + ' C / ' + kf(B.pOI) + ' P', 'week: calls <span style="color:' + col(B.cOI5) + '">' + sg(B.cOI5, 0) + '</span> · puts <span style="color:' + col(B.pOI5) + '">' + sg(B.pOI5, 0) + '</span>') + '</div>';
    h += '<div class="dk-grid"><div class="dk-card"><div class="dk-sec">Desk brief</div>' + B.brief.map(function (b) { return '<div class="dk-h">' + b.h + '</div><p>' + md(b.t) + '</p>'; }).join('') + '</div>' +
      '<div class="dk-card"><div class="dk-sec">Signal board</div><table class="dk-t"><thead><tr><th>Signal</th><th>Read</th><th style="text-align:left">Why</th></tr></thead><tbody>' +
      B.factors.map(function (f) { return '<tr><td class="b">' + f.factor + '</td><td><span class="dk-tag ' + (f.tilt === 'bullish' ? 'up' : f.tilt === 'bearish' ? 'dn' : 'neu') + '">' + f.tilt + '</span></td><td class="l">' + f.text + '</td></tr>'; }).join('') +
      '</tbody></table><div class="dk-note">Cotton’s vol tends to rise in rallies (unlike stocks), so a vol pick-up is not read as “fear”. Signals combine price, vol, skew and positioning; readings on put/call and open-interest flow rest on a short history.</div></div></div>';
    h += '<div class="dk-grid"><div class="dk-card"><div class="dk-sec"><span>Implied vs realized vol</span><span class="dk-seg" id="dk-ivr">' + (B.ivlong ? '<button data-r="long" class="' + (ivRange === 'long' ? 'on' : '') + '">5 years</button>' : '') + '<button data-r="short" class="' + (ivRange === 'short' || !B.ivlong ? 'on' : '') + '">ICE archive</button></span></div><div class="dk-cb"><canvas id="dk-iv"></canvas></div>' +
      '<div class="dk-note">' + (B.ivlong_source ? 'Long history: ' + B.ivlong_source + '. ' : '') + 'Realized = 20-day close-to-close vol of the front contract (roll days excluded).</div></div>' +
      '<div class="dk-card"><div class="dk-sec">Term structure — ATM vol by expiry</div><div class="dk-cb"><canvas id="dk-term"></canvas></div><div class="dk-note">Today vs ' + (B.wk_ref || 'a week ago') + '.</div></div></div>';
    h += '<div class="dk-grid"><div class="dk-card"><div class="dk-sec">Volatility smile — ' + B.front_label + (B.smile.second_label ? ' & ' + B.smile.second_label : '') + '</div><div class="dk-cb"><canvas id="dk-smile"></canvas></div><div class="dk-note">Out-of-the-money options: puts below the futures, calls above. A smile rising to the right means upside calls are priced richer.</div></div>' +
      '<div class="dk-card"><div class="dk-sec">Skew & positioning history</div><div class="dk-cb"><canvas id="dk-skew"></canvas></div><div class="dk-note">25-delta risk reversal (call vol − put vol) and put/call open interest, all expiries.</div></div></div>';
    if (B.expiries && B.expiries.length) {
      var cs = function (v, d, inv) { return v == null ? '<span class="mu">–</span>' : '<span style="color:' + col(v, inv) + '">' + sg(v, d) + '</span>'; };
      var ks = function (v) { return v == null ? '<span class="mu">–</span>' : '<span style="color:' + col(v) + '">' + (v > 0 ? '+' : '') + kf(v) + '</span>'; };
      h += '<div class="dk-card"><div class="dk-sec">By expiry — past week (' + (B.wk_ref || '') + ' → ' + B.date + ')</div><div style="overflow-x:auto"><table class="dk-t dk-x"><thead><tr>' +
        '<th>Expiry</th><th>Futures</th><th>w/w</th><th>Fut OI w/w</th><th>Futures read</th><th>Spread to next</th><th>w/w</th><th>ATM vol</th><th>w/w</th><th>25Δ RR</th><th>w/w</th><th>Realized</th><th>IV − RV</th><th>Call OI w/w</th><th>Put OI w/w</th><th>Flow</th><th>Call wall</th><th>Put wall</th><th>Max gamma</th><th>Max pain</th><th>±1σ to expiry</th></tr></thead><tbody>' +
        B.expiries.map(function (r) {
          return '<tr><td class="b">' + r.label + ' <span class="mu">' + r.dte + 'd</span></td><td class="b">' + f1(r.F, 2) + '</td><td>' + cs(r.dF, 2) + '</td><td>' + ks(r.dFutOI) + '</td><td>' + (r.fut_read || '–') + '</td>' +
            '<td>' + (r.spread == null ? '–' : sg(r.spread, 2) + ' <span class="mu">vs ' + r.spread_vs + '</span>') + '</td><td>' + cs(r.dSpread, 2) + '</td>' +
            '<td class="b">' + f1(r.atm) + '%</td><td>' + cs(r.dIV) + '</td><td>' + sg(r.rr25) + '</td><td>' + cs(r.dRR) + '</td><td>' + (r.rv == null ? '–' : f1(r.rv) + '%') + '</td><td>' + cs(r.vrp, 1, true) + '</td>' +
            '<td>' + ks(r.dcOI) + '</td><td>' + ks(r.dpOI) + '</td><td><span class="dk-tag ' + (r.flow === 'bullish' ? 'up' : r.flow === 'bearish' ? 'dn' : 'neu') + '" title="' + r.flow_why + '">' + r.flow + '</span></td>' +
            '<td style="color:#4f8ef7">' + (r.call_wall == null ? '–' : r.call_wall) + '</td><td style="color:#e05d5d">' + (r.put_wall == null ? '–' : r.put_wall) + '</td><td style="color:#bc8cff">' + (r.gamma_peak == null ? '–' : r.gamma_peak) + '</td><td style="color:#f0b429">' + (r.max_pain == null ? '–' : r.max_pain) + '</td>' +
            '<td>' + (r.em_exp == null ? '–' : '±' + f1(r.em_exp, 2) + ' <span class="mu">(' + f1(r.F - r.em_exp, 1) + '–' + f1(r.F + r.em_exp, 1) + ')</span>') + '</td></tr>';
        }).join('') + '</tbody></table></div><div class="dk-note">Futures read: price and open interest together — new buying (both up), short covering (price up, OI down), new selling (price down, OI up), long liquidation (both down). Spread = this contract minus the next; rising = nearby firming. Flow combines call vs put open-interest builds, skew change and the price/vol mix — hover the tag for the reasons. Realized vol from this contract’s daily settlements in the archive.</div></div>';
    }
    var mp = B.maps[mapIdx] || B.maps[0];
    h += '<div class="dk-card"><div class="dk-sec"><span>Positioning map — open interest & gamma by strike</span><span class="dk-seg" id="dk-mapsel">' + B.maps.map(function (m, i) { return '<button data-i="' + i + '" class="' + (i === mapIdx ? 'on' : '') + '">' + m.label + '</button>'; }).join('') + '</span></div>' +
      (mp ? '<div class="dk-mapk"><span>Futures <b>' + f1(mp.F, 2) + '</b></span><span class="c">Call wall <b>' + mp.call_wall + '</b></span><span class="p">Put wall <b>' + mp.put_wall + '</b></span><span>Max pain <b>' + mp.max_pain + '</b></span><span>Gamma peak <b>' + mp.gamma_peak + '</b></span><span>' + mp.dte + ' days to expiry</span></div>' : '') +
      '<div class="dk-grid2"><div><div class="dk-cb tall"><canvas id="dk-oi"></canvas></div></div><div><div class="dk-cb tall"><canvas id="dk-gam"></canvas></div></div></div>' +
      '<div class="dk-note">Left: open interest by strike (calls up, puts down) with today’s change. Right: gross gamma — futures-equivalent lots that change hands per 1¢ move if positions are hedged; the biggest concentrations act as magnets or speed bumps, especially near expiry.</div></div>';
    h += '<div class="dk-card"><div class="dk-sec">Daily flow — volume and open interest</div><div class="dk-cb"><canvas id="dk-flow"></canvas></div></div>';
    el.innerHTML = h;
    draw();
  }

  function draw() {
    var B = D, H = B.hist;
    // IV vs RV
    kill('iv');
    var ds = [];
    if (ivRange === 'long' && B.ivlong) {
      ds.push({ label: 'Implied vol (front, weekly)', data: B.ivlong.map(function (p) { return { x: p[0], y: p[1] }; }), borderColor: C.atm, backgroundColor: 'rgba(240,180,41,.08)', fill: true, pointRadius: 0, borderWidth: 1.6, tension: .2, spanGaps: false });
    } else {
      ds.push({ label: 'ATM implied vol', data: H.dates.map(function (d, i) { return { x: d, y: H.atm[i] }; }), borderColor: C.atm, pointRadius: 2.5, borderWidth: 2, spanGaps: false });
    }
    if (H.rv20) ds.push({ label: 'Realized vol (20d)', data: H.rv20.filter(function (p) { return ivRange === 'long' || p[0] >= H.dates[0]; }).map(function (p) { return { x: p[0], y: p[1] }; }), borderColor: C.rv, borderDash: [4, 3], pointRadius: 0, borderWidth: 1.4 });
    var labs = {}; ds.forEach(function (d) { d.data.forEach(function (p) { labs[p.x] = 1; }); });
    charts.iv = new Chart($('dk-iv'), { type: 'line', data: { labels: Object.keys(labs).sort(), datasets: ds },
      options: base({ scales: { x: { ticks: { color: C.txt, maxTicksLimit: 8, font: { size: 10 } }, grid: { color: C.grid } }, y: { ticks: { color: C.txt, callback: function (v) { return v + '%'; } }, grid: { color: C.grid } } } }) });
    // term
    kill('term');
    charts.term = new Chart($('dk-term'), { type: 'line', data: { datasets: [
      { label: 'Today', data: B.term.map(function (t) { return { x: t.dte, y: t.atm, l: t.label }; }), borderColor: C.atm, backgroundColor: C.atm, pointRadius: 4, borderWidth: 2.5 },
      { label: B.wk_ref || 'Week ago', data: (B.term_wk || []).map(function (t) { return { x: t.dte + 7, y: t.atm, l: t.label }; }), borderColor: C.wk, backgroundColor: C.wk, pointRadius: 3, borderDash: [4, 3], borderWidth: 1.5 }] },
      options: base({ scales: { x: { type: 'linear', title: { display: true, text: 'Days to option expiry', color: C.txt }, ticks: { color: C.txt }, grid: { color: C.grid } }, y: { ticks: { color: C.txt, callback: function (v) { return v + '%'; } }, grid: { color: C.grid } } },
        plugins: { legend: { labels: { color: C.txt, boxWidth: 10 } }, tooltip: { callbacks: { label: function (c) { return ' ' + c.dataset.label + ' ' + c.raw.l + ': ' + c.parsed.y.toFixed(1) + '%'; } } } } }) });
    // smile
    kill('smile');
    var sm = [{ label: B.front_label + ' today', data: B.smile.front.map(function (p) { return { x: p[0], y: p[1] }; }), borderColor: C.atm, pointRadius: 0, borderWidth: 2.5, tension: .3 }];
    if (B.smile.front_wk && B.smile.front_wk.length) sm.push({ label: B.front_label + ' week ago', data: B.smile.front_wk.map(function (p) { return { x: p[0], y: p[1] }; }), borderColor: C.wk, borderDash: [4, 3], pointRadius: 0, borderWidth: 1.5, tension: .3 });
    if (B.smile.second && B.smile.second.length) sm.push({ label: B.smile.second_label + ' today', data: B.smile.second.map(function (p) { return { x: p[0], y: p[1] }; }), borderColor: '#bc8cff', pointRadius: 0, borderWidth: 1.8, tension: .3 });
    charts.smile = new Chart($('dk-smile'), { type: 'line', data: { datasets: sm }, plugins: [vlines], options: base({ scales: { x: { type: 'linear', title: { display: true, text: 'Strike', color: C.txt }, ticks: { color: C.txt }, grid: { color: C.grid } }, y: { ticks: { color: C.txt, callback: function (v) { return v + '%'; } }, grid: { color: C.grid } } },
      plugins: { vlines: { lines: [{ v: B.F, c: '#e6edf3', t: 'F ' + f1(B.F, 2), dash: [3, 3], w: 1 }] }, legend: { labels: { color: C.txt, boxWidth: 10 } }, tooltip: { callbacks: { title: function (c) { return 'Strike ' + c[0].parsed.x; }, label: function (c) { return ' ' + c.dataset.label + ': ' + c.parsed.y.toFixed(1) + '%'; } } } } }) });
    // skew & P/C
    kill('skew');
    charts.skew = new Chart($('dk-skew'), { data: { labels: H.dates, datasets: [
      { type: 'bar', label: '25Δ risk reversal (vol)', data: H.rr25, backgroundColor: H.rr25.map(function (v) { return v == null ? 'transparent' : v >= 0 ? 'rgba(79,142,247,.7)' : 'rgba(224,93,93,.7)'; }), yAxisID: 'y' },
      { type: 'line', label: 'Put/call open interest', data: H.pc_oi, borderColor: C.atm, pointRadius: 2, borderWidth: 2, yAxisID: 'y2' }] },
      options: base({ scales: { x: { ticks: { color: C.txt, maxTicksLimit: 8, font: { size: 10 } }, grid: { color: C.grid } }, y: { ticks: { color: C.txt }, grid: { color: C.grid }, title: { display: true, text: 'RR (vol pts)', color: C.txt } }, y2: { position: 'right', ticks: { color: C.atm }, grid: { drawOnChartArea: false }, title: { display: true, text: 'P/C OI', color: C.atm } } } }) });
    // strike map
    var mp = B.maps[mapIdx] || B.maps[0];
    kill('oi'); kill('gam');
    if (mp) {
      var R = mp.rows, lines = [{ v: mp.F, c: '#e6edf3', t: 'F', dash: [3, 3], w: 1 }, { v: mp.call_wall, c: C.call, t: 'call wall', w: 1.2 }, { v: mp.put_wall, c: C.put, t: 'put wall', w: 1.2 }, { v: mp.max_pain, c: C.atm, t: 'max pain', dash: [2, 3], w: 1.2 }];
      charts.oi = new Chart($('dk-oi'), { type: 'bar', data: { datasets: [
        { label: 'Call OI', data: R.map(function (r) { return { x: r.K, y: r.cOI }; }), backgroundColor: 'rgba(79,142,247,.75)', barPercentage: 1, categoryPercentage: .9 },
        { label: 'Put OI', data: R.map(function (r) { return { x: r.K, y: -r.pOI }; }), backgroundColor: 'rgba(224,93,93,.75)', barPercentage: 1, categoryPercentage: .9 },
        { type: 'line', label: 'Call Δ OI today', data: R.map(function (r) { return { x: r.K, y: r.cChg }; }), borderColor: '#9cc2ff', pointRadius: 0, borderWidth: 1.2, showLine: true },
        { type: 'line', label: 'Put Δ OI today', data: R.map(function (r) { return { x: r.K, y: -r.pChg }; }), borderColor: '#ffaaaa', pointRadius: 0, borderWidth: 1.2, showLine: true }] }, plugins: [vlines],
        options: base({ interaction: { mode: 'nearest', axis: 'x', intersect: false }, scales: { x: { type: 'linear', offset: false, title: { display: true, text: 'Strike', color: C.txt }, ticks: { color: C.txt }, grid: { color: C.grid } }, y: { stacked: false, ticks: { color: C.txt, callback: function (v) { return kf(Math.abs(v)); } }, grid: { color: C.grid }, title: { display: true, text: 'Lots (puts shown below zero)', color: C.txt } } },
          plugins: { vlines: { lines: lines }, legend: { labels: { color: C.txt, boxWidth: 10 } }, tooltip: { callbacks: { title: function (c) { return 'Strike ' + c[0].parsed.x; }, label: function (c) { return ' ' + c.dataset.label + ': ' + Math.abs(c.parsed.y).toLocaleString(); } } } } }) });
      charts.gam = new Chart($('dk-gam'), { type: 'bar', data: { datasets: [
        { label: 'Call gamma', data: R.map(function (r) { return { x: r.K, y: r.cGam }; }), backgroundColor: 'rgba(79,142,247,.75)', stack: 'g', barPercentage: 1, categoryPercentage: .9 },
        { label: 'Put gamma', data: R.map(function (r) { return { x: r.K, y: r.pGam }; }), backgroundColor: 'rgba(224,93,93,.75)', stack: 'g', barPercentage: 1, categoryPercentage: .9 }] }, plugins: [vlines],
        options: base({ interaction: { mode: 'nearest', axis: 'x', intersect: false }, scales: { x: { type: 'linear', stacked: true, title: { display: true, text: 'Strike', color: C.txt }, ticks: { color: C.txt }, grid: { color: C.grid } }, y: { stacked: true, ticks: { color: C.txt }, grid: { color: C.grid }, title: { display: true, text: 'Futures lots per 1¢ move', color: C.txt } } },
          plugins: { vlines: { lines: [lines[0], { v: mp.gamma_peak, c: '#bc8cff', t: 'gamma peak', w: 1.2 }] }, legend: { labels: { color: C.txt, boxWidth: 10 } } } }) });
    }
    // flow
    kill('flow');
    charts.flow = new Chart($('dk-flow'), { data: { labels: H.dates, datasets: [
      { type: 'bar', label: 'Call volume', data: H.cVol, backgroundColor: 'rgba(79,142,247,.7)', stack: 'v' },
      { type: 'bar', label: 'Put volume', data: H.pVol.map(function (v) { return -v; }), backgroundColor: 'rgba(224,93,93,.7)', stack: 'v' },
      { type: 'line', label: 'Call OI', data: H.cOI, borderColor: '#9cc2ff', pointRadius: 0, borderWidth: 1.6, yAxisID: 'y2' },
      { type: 'line', label: 'Put OI', data: H.pOI, borderColor: '#ffaaaa', pointRadius: 0, borderWidth: 1.6, yAxisID: 'y2' }] },
      options: base({ scales: { x: { stacked: true, ticks: { color: C.txt, maxTicksLimit: 10, font: { size: 10 } }, grid: { color: C.grid } }, y: { stacked: true, ticks: { color: C.txt, callback: function (v) { return kf(Math.abs(v)); } }, grid: { color: C.grid }, title: { display: true, text: 'Volume (puts below zero)', color: C.txt } }, y2: { position: 'right', ticks: { color: C.txt, callback: function (v) { return kf(v); } }, grid: { drawOnChartArea: false }, title: { display: true, text: 'Open interest', color: C.txt } } },
        plugins: { legend: { labels: { color: C.txt, boxWidth: 10 } }, tooltip: { callbacks: { label: function (c) { return ' ' + c.dataset.label + ': ' + Math.abs(c.parsed.y).toLocaleString(); } } } } }) });
  }

  function load(t) {
    T = t || T; mapIdx = 0;
    var el = $('desk-body'); if (!el) return;
    el.innerHTML = '<div class="dk-empty">Loading vol desk…</div>';
    fetch('./data/web/' + T + '_desk.json?t=' + Date.now()).then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) { D = d; ivRange = d.ivlong ? 'long' : 'short'; render(); })
      .catch(function () { el.innerHTML = '<div class="dk-empty">Vol desk not built yet for ' + T + '.</div>'; });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('#dk-mapsel button'); if (b) { mapIdx = +b.getAttribute('data-i'); render(); return; }
    var r = e.target.closest && e.target.closest('#dk-ivr button'); if (r) { ivRange = r.getAttribute('data-r'); render(); }
  });
  window.Desk = { load: load, redraw: function () { if (D) draw(); } };
  // follow the commodity tabs in the header
  var orig = window.switchCommodity;
  if (typeof orig === 'function') window.switchCommodity = function (t) { var x = orig.apply(this, arguments); load(t); return x; };
  document.addEventListener('DOMContentLoaded', function () { load('CT'); });
  if (document.readyState !== 'loading') load('CT');
})();
