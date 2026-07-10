"""Self-contained operator console HTML — no CDN, no external assets."""

# Single page; inline CSS/JS. Fetches GET /console/data every 10s. READ-ONLY.

CONSOLE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentGRIT Console · read-only</title>
<style>
:root {
  --bg:#0f1218; --panel:#171b24; --border:#2a3140; --text:#e6eaf2; --muted:#8b93a7;
  --proceed:#3ecf8e; --refused:#f07178; --escalated:#e6b450; --contested:#c792ea;
  --unknown:#6b7280; --accent:#5b9fd4;
}
* { box-sizing:border-box; }
body { margin:0; font:13px/1.45 ui-sans-serif, system-ui, -apple-system, sans-serif;
  background:var(--bg); color:var(--text); }
header.sticky { position:sticky; top:0; z-index:10; background:#0c0f14ee;
  border-bottom:1px solid var(--border); backdrop-filter:blur(6px);
  padding:10px 16px; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
header h1 { font-size:14px; margin:0; font-weight:600; letter-spacing:.02em; }
header .badge { font-size:11px; color:var(--muted); border:1px solid var(--border);
  border-radius:999px; padding:2px 8px; }
header .status { margin-left:auto; font-size:11px; color:var(--muted); }
header .status.live { color:var(--proceed); }
header .status.stale { color:var(--escalated); }
header .status.err { color:var(--refused); }
main { padding:12px 16px 32px; display:grid;
  grid-template-columns: 1.4fr 1fr; gap:12px; }
@media (max-width:900px) { main { grid-template-columns:1fr; } }
section { background:var(--panel); border:1px solid var(--border); border-radius:8px;
  padding:10px 12px; min-height:80px; }
section h2 { margin:0 0 8px; font-size:11px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--muted); font-weight:600; }
.row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
.pill { font-size:11px; padding:2px 8px; border-radius:4px; background:#222836; color:var(--muted); }
.pill b { color:var(--text); font-weight:600; }
.stream { max-height:360px; overflow:auto; }
.item { border-top:1px solid var(--border); padding:8px 0; }
.item:first-child { border-top:0; }
.disp { font-size:10px; font-weight:700; letter-spacing:.04em; padding:1px 6px;
  border-radius:3px; display:inline-block; }
.disp.proceed { background:#143528; color:var(--proceed); }
.disp.refused { background:#3a1a1e; color:var(--refused); }
.disp.escalated { background:#3a3014; color:var(--escalated); }
.disp.contested { background:#2a1f3a; color:var(--contested); }
.disp.unknown { background:#222; color:var(--unknown); }
.meta { color:var(--muted); font-size:11px; margin-top:2px; }
.action { margin-top:3px; word-break:break-word; }
.empty { color:var(--muted); font-style:italic; padding:8px 0; }
.bar-wrap { margin:4px 0; }
.bar { display:flex; align-items:center; gap:8px; margin:3px 0; font-size:12px; }
.bar .name { width:90px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.bar .track { flex:1; height:8px; background:#0f1218; border-radius:4px; overflow:hidden; }
.bar .fill { height:100%; background:var(--accent); }
.bar .n { width:28px; text-align:right; color:var(--muted); }
footer { grid-column:1/-1; color:var(--muted); font-size:11px; text-align:center; padding:8px; }
</style>
</head>
<body>
<header class="sticky">
  <h1>AgentGRIT Console</h1>
  <span class="badge">READ-ONLY · no actions</span>
  <span class="status" id="conn">loading…</span>
</header>
<main>
  <section style="grid-column:1/-1">
    <h2>Today · debrief counts</h2>
    <div class="row" id="debrief"></div>
  </section>
  <section>
    <h2>Decision stream</h2>
    <div class="stream" id="decisions"></div>
  </section>
  <section>
    <h2>Escalations queue</h2>
    <div class="stream" id="escalations"></div>
  </section>
  <section>
    <h2>Router · by provider</h2>
    <div id="router"></div>
  </section>
  <section>
    <h2>Observe · last run</h2>
    <div id="observe"></div>
    <h2 style="margin-top:14px">Trust</h2>
    <div id="trust"></div>
  </section>
  <footer>Renders logs only · never POSTs · refresh ~10s · missing logs show empty sections</footer>
</main>
<script>
(function(){
  const INTERVAL = 10000;
  let lastOk = 0;
  const el = id => document.getElementById(id);
  function dispClass(d){
    d = (d||'unknown').toLowerCase();
    if (['proceed','refused','escalated','contested'].indexOf(d)>=0) return d;
    return 'unknown';
  }
  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }
  function render(data){
    // debrief
    const d = data.debrief || {};
    const disp = d.dispositions_today || {};
    el('debrief').innerHTML = [
      pill('day', d.day||'—'),
      pill('decisions today', d.decision_count_today||0),
      pill('file total', d.decisions_total_file||0),
      pill('research paid', d.research_paid_today||0),
      ...Object.keys(disp).map(k => pill(k, disp[k]))
    ].join('');
    // decisions
    const decs = data.decisions || [];
    el('decisions').innerHTML = decs.length ? decs.map(r => `
      <div class="item">
        <span class="disp ${dispClass(r.disposition)}">${esc(r.disposition).toUpperCase()}</span>
        <span class="meta">${esc(r.ts)} · ${esc(r.authorized_by||'')}</span>
        <div class="action">${esc(r.action)}</div>
        <div class="meta">${esc(r.rationale)}</div>
      </div>`).join('') : '<div class="empty">No decisions yet (or decisions.jsonl missing)</div>';
    // escalations
    const escRows = data.escalations || [];
    el('escalations').innerHTML = escRows.length ? escRows.map(r => `
      <div class="item">
        <span class="disp escalated">${esc(r.status||r.event)}</span>
        <span class="meta">${esc(r.ts)} · ${esc(r.id)}</span>
        <div class="action">${esc(r.requester)} · ${esc(r.category)} · risk=${esc(r.risk_level)}</div>
        <div class="meta">expires ${esc(r.expires_at||'—')}</div>
      </div>`).join('') : '<div class="empty">No escalation events (or escalations.jsonl missing)</div>';
    // router
    const by = (data.router && data.router.by_provider) || {};
    const total = (data.router && data.router.total) || 0;
    const keys = Object.keys(by);
    if (!keys.length) {
      el('router').innerHTML = '<div class="empty">No router.jsonl activity</div>';
    } else {
      const max = Math.max(...keys.map(k => by[k]), 1);
      el('router').innerHTML = `<div class="meta" style="margin-bottom:6px">last window · n=${total}</div>` +
        keys.map(k => `
        <div class="bar">
          <div class="name" title="${esc(k)}">${esc(k)}</div>
          <div class="track"><div class="fill" style="width:${(100*by[k]/max).toFixed(0)}%"></div></div>
          <div class="n">${by[k]}</div>
        </div>`).join('');
    }
    // observe
    const o = data.observe || {};
    if (!o.available) {
      el('observe').innerHTML = '<div class="empty">No observe snapshot yet (run make observe)</div>';
    } else {
      el('observe').innerHTML = [
        pill('feed', o.feed||'all'),
        pill('events', o.event_count||0),
        pill('actionable', o.actionable_count||0),
        pill('blocked', o.non_actionable_count||0),
        pill('verdict', o.verdict||'—'),
        `<div class="meta" style="margin-top:6px">${esc(o.ts||'')}</div>`
      ].join(' ');
    }
    // trust
    const t = data.trust || {};
    const bl = t.by_level || {};
    el('trust').innerHTML = Object.keys(bl).length
      ? Object.keys(bl).map(k => pill(k, bl[k])).join('') +
        `<div class="meta" style="margin-top:6px">promotions=${esc(t.recent_promotions)} demotions=${esc(t.recent_demotions)}</div>`
      : '<div class="empty">No trust history yet</div>';
    // missing
    if ((data.missing_logs||[]).length) {
      el('conn').title = 'missing: ' + data.missing_logs.join(', ');
    }
  }
  function pill(k,v){ return `<span class="pill">${esc(k)}: <b>${esc(v)}</b></span>`; }
  async function tick(){
    const conn = el('conn');
    try {
      const r = await fetch('/console/data', {cache:'no-store'});
      if (!r.ok) throw new Error('HTTP '+r.status);
      const data = await r.json();
      render(data);
      lastOk = Date.now();
      conn.textContent = 'live · ' + (data.ts||'').slice(11,19) + 'Z';
      conn.className = 'status live';
    } catch (e) {
      const age = lastOk ? Math.round((Date.now()-lastOk)/1000)+'s ago' : 'never';
      conn.textContent = 'error · last ok '+age;
      conn.className = 'status err';
    }
  }
  // stale indicator if tab backgrounded
  setInterval(() => {
    if (lastOk && Date.now()-lastOk > INTERVAL*2.5) {
      const conn = el('conn');
      if (!conn.className.includes('err')) {
        conn.className = 'status stale';
        conn.textContent = 'stale · retrying';
      }
    }
  }, 3000);
  tick();
  setInterval(tick, INTERVAL);
})();
</script>
</body>
</html>
"""
