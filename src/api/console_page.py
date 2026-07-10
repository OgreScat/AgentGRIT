"""Multi-screen operator console HTML — self-contained, no CDN. READ-ONLY."""

# Single-page app: left nav + center + right context rail.
# Fetches GET /console/data?screen=…  Never POSTs.

CONSOLE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentGRIT Ops Console · read-only</title>
<style>
:root {
  --bg:#0c0f14; --panel:#151922; --panel2:#1a1f2b; --border:#2a3140;
  --text:#e6eaf2; --muted:#8b93a7; --accent:#5b9fd4;
  --proceed:#3ecf8e; --refused:#f07178; --escalated:#e6b450; --contested:#c792ea;
  --nav-w:168px; --rail-w:280px;
}
* { box-sizing:border-box; }
body { margin:0; font:12.5px/1.45 ui-sans-serif, system-ui, -apple-system, sans-serif;
  background:var(--bg); color:var(--text); height:100vh; display:flex; flex-direction:column; }
header.top { display:flex; align-items:center; gap:12px; padding:8px 14px;
  border-bottom:1px solid var(--border); background:#0a0c10ee; flex-shrink:0; }
header h1 { font-size:13px; margin:0; font-weight:600; }
.badge { font-size:10px; color:var(--muted); border:1px solid var(--border);
  border-radius:999px; padding:2px 8px; }
.badge.warn { border-color:var(--escalated); color:var(--escalated); }
header .status { margin-left:auto; font-size:11px; color:var(--muted); }
header .status.live { color:var(--proceed); }
header .status.err { color:var(--refused); }
header .status.stale { color:var(--escalated); }
.shell { display:flex; flex:1; min-height:0; }
nav.side { width:var(--nav-w); border-right:1px solid var(--border); background:var(--panel);
  padding:10px 0; flex-shrink:0; overflow:auto; }
nav.side button { display:block; width:100%; text-align:left; background:transparent;
  border:0; color:var(--muted); padding:9px 14px; font:inherit; cursor:pointer; }
nav.side button:hover { color:var(--text); background:#1c2230; }
nav.side button.active { color:var(--text); background:#222836; border-left:2px solid var(--accent); }
nav.side .hint { padding:12px 14px; font-size:10px; color:var(--muted); line-height:1.4; }
center-pane { flex:1; display:flex; flex-direction:column; min-width:0; }
.center { flex:1; overflow:auto; padding:12px 14px; }
.rail { width:var(--rail-w); border-left:1px solid var(--border); background:var(--panel);
  padding:12px; overflow:auto; flex-shrink:0; }
@media (max-width:960px) {
  .rail { display:none; }
  nav.side { width:120px; }
}
h2 { margin:0 0 8px; font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); font-weight:600; }
.kpis { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
.kpi { background:var(--panel); border:1px solid var(--border); border-radius:8px;
  padding:10px 12px; min-width:110px; }
.kpi .v { font-size:18px; font-weight:600; }
.kpi .l { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
.table { width:100%; border-collapse:collapse; font-size:12px; }
.table th { text-align:left; color:var(--muted); font-weight:600; font-size:10px;
  text-transform:uppercase; letter-spacing:.04em; padding:6px 8px; border-bottom:1px solid var(--border); }
.table td { padding:7px 8px; border-bottom:1px solid var(--border); vertical-align:top; }
.table tr { cursor:pointer; }
.table tr:hover { background:#1c2230; }
.table tr.sel { background:#222836; }
.disp { font-size:10px; font-weight:700; letter-spacing:.03em; padding:1px 6px; border-radius:3px; }
.disp.proceed { background:#143528; color:var(--proceed); }
.disp.refused { background:#3a1a1e; color:var(--refused); }
.disp.escalated { background:#3a3014; color:var(--escalated); }
.disp.contested { background:#2a1f3a; color:var(--contested); }
.disp.unknown,.disp.pending { background:#222; color:var(--muted); }
.meta { color:var(--muted); font-size:11px; }
.item { border-bottom:1px solid var(--border); padding:8px 0; }
.empty { color:var(--muted); font-style:italic; padding:12px 4px; }
.tabs { display:flex; gap:4px; margin-bottom:10px; flex-wrap:wrap; }
.tabs button { background:var(--panel2); border:1px solid var(--border); color:var(--muted);
  border-radius:4px; padding:4px 10px; font:inherit; cursor:pointer; }
.tabs button.active { color:var(--text); border-color:var(--accent); }
.bar { display:flex; align-items:center; gap:8px; margin:4px 0; }
.bar .name { width:88px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.bar .track { flex:1; height:8px; background:#0f1218; border-radius:4px; overflow:hidden; }
.bar .fill { height:100%; background:var(--accent); }
.bar .n { width:32px; text-align:right; color:var(--muted); }
.note { font-size:11px; color:var(--muted); border:1px dashed var(--border); border-radius:6px;
  padding:8px 10px; margin:8px 0; }
.filters { display:flex; gap:8px; margin-bottom:8px; flex-wrap:wrap; }
.filters select { background:#0f1218; color:var(--text); border:1px solid var(--border);
  border-radius:4px; padding:3px 6px; font:inherit; }
.timeline .item .kind { font-size:10px; color:var(--accent); text-transform:uppercase; }
pre.why { white-space:pre-wrap; word-break:break-word; font-size:11px; color:var(--muted);
  background:#0f1218; padding:8px; border-radius:6px; max-height:200px; overflow:auto; }
</style>
</head>
<body>
<header class="top">
  <h1>AgentGRIT Ops</h1>
  <span class="badge">READ-ONLY · no actions</span>
  <span class="badge warn">Approvals → CLI / Telegram</span>
  <span class="status" id="conn">loading…</span>
</header>
<div class="shell">
  <nav class="side" id="nav"></nav>
  <div style="flex:1;display:flex;flex-direction:column;min-width:0">
    <div class="center" id="center"></div>
  </div>
  <aside class="rail" id="rail">
    <h2>Context</h2>
    <div class="empty" id="rail-body">Select a row for detail.</div>
  </aside>
</div>
<script>
(function(){
  const SCREENS = [
    {id:'overview', label:'Overview'},
    {id:'tasks', label:'Tasks'},
    {id:'governance', label:'Governance'},
    {id:'research', label:'Research'},
    {id:'models', label:'Models & Cost'},
    {id:'audit', label:'Audit'},
  ];
  let screen = 'overview';
  let cache = {};
  let selected = null;
  let lastOk = 0;
  let govTab = 'escalations';
  let filterDisp = '';
  let filterProv = '';

  const el = id => document.getElementById(id);
  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }
  function dispClass(d){
    d = (d||'unknown').toLowerCase();
    if (['proceed','refused','escalated','contested','pending'].indexOf(d)>=0) return d;
    return 'unknown';
  }
  function pill(k,v){ return `<span class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(k)}</div></span>`; }

  // nav
  el('nav').innerHTML = SCREENS.map(s =>
    `<button data-s="${s.id}" class="${s.id===screen?'active':''}">${s.label}</button>`
  ).join('') + `<div class="hint">Renders logs only.<br/>Never POSTs.<br/>Approvals out of scope.</div>`;
  el('nav').onclick = e => {
    const b = e.target.closest('button[data-s]');
    if (!b) return;
    screen = b.getAttribute('data-s');
    selected = null;
    [...el('nav').querySelectorAll('button')].forEach(x => x.classList.toggle('active', x.dataset.s===screen));
    render();
    if (!cache[screen]) tick();
  };

  function renderRail(row){
    const body = el('rail-body');
    if (!row) { body.innerHTML = '<div class="empty">Select a row for detail.</div>'; return; }
    let html = '';
    if (row.action || row.question) {
      html += `<div class="meta">Task / question</div><div style="margin:4px 0 10px;font-weight:600">${esc(row.action||row.question)}</div>`;
    }
    if (row.disposition) html += `<div class="meta">Disposition</div><div style="margin-bottom:8px"><span class="disp ${dispClass(row.disposition)}">${esc(row.disposition).toUpperCase()}</span></div>`;
    if (row.provider) html += `<div class="meta">Provider</div><div style="margin-bottom:8px">${esc(row.provider)}</div>`;
    if (row.bylaw_action) html += `<div class="meta">Bylaw</div><div style="margin-bottom:8px">${esc(row.bylaw_action)} — ${esc(row.bylaw_reason||'')}</div>`;
    if (row.evidence_verdict) html += `<div class="meta">Evidence</div><div style="margin-bottom:8px">${esc(row.evidence_verdict)} score=${esc(row.evidence_score)}</div>`;
    if (row.route_reason || row.reason) html += `<div class="meta">Why this model / route</div><pre class="why">${esc(row.route_reason||row.reason||'')}</pre>`;
    if (row.rationale) html += `<div class="meta">Rationale</div><div class="meta" style="margin-bottom:8px">${esc(row.rationale)}</div>`;
    if (row.authorized_by) html += `<div class="meta">Authorized by</div><div>${esc(row.authorized_by)}</div>`;
    if (row.confidence_band) html += `<div class="meta" style="margin-top:8px">Brief band</div><div>${esc(row.confidence_band)} · gate=${esc(row.autonomy_gate||'—')}</div>`;
    if (row.brief_hint) html += `<div class="note" style="margin-top:10px">${esc(row.brief_hint)}</div>`;
    html += `<div class="note" style="margin-top:12px">Open domain brief UI: <code>/brief</code> (also read-only). Approvals: CLI / Telegram only.</div>`;
    body.innerHTML = html || '<div class="empty">No detail fields.</div>';
  }

  function renderOverview(d){
    const k = d.kpis || {};
    const disp = k.dispositions_today || {};
    let html = `<div class="kpis">
      ${pill('decisions today', k.decisions_today||0)}
      ${pill('pending esc.', k.pending_escalations||0)}
      ${pill('router n', k.router_total||0)}
      ${pill('est. cost Σ', (k.router_cost_sum||0).toPrecision ? Number(k.router_cost_sum||0).toPrecision(3) : 0)}
      ${pill('trust ↑', k.trust_promotions||0)}
      ${pill('trust ↓', k.trust_demotions||0)}
    </div>`;
    html += `<div class="kpis">${Object.keys(disp).map(x=>pill(x, disp[x])).join('')}</div>`;
    if (k.last_blocked) {
      html += `<div class="note">Last blocked: <b>${esc(k.last_blocked.action)}</b> — ${esc(k.last_blocked.reason)}</div>`;
    }
    const agents = k.active_agent_hints || {};
    if (Object.keys(agents).length) {
      html += `<h2>Agent hints (from authorized_by)</h2><div class="kpis">${Object.keys(agents).map(a=>pill(a, agents[a])).join('')}</div>`;
    } else {
      html += `<div class="note">Active-agent count is inferred from recent authorized_by tags — no dedicated agent process log.</div>`;
    }
    html += `<h2>Recent activity</h2><div class="timeline">`;
    const tl = d.timeline || [];
    if (!tl.length) html += `<div class="empty">No recent activity</div>`;
    tl.forEach(t => {
      html += `<div class="item"><span class="kind">${esc(t.kind)}</span>
        <span class="disp ${dispClass(t.label)}">${esc(t.label)}</span>
        <span class="meta">${esc(t.ts)}</span>
        <div>${esc(t.text)}</div></div>`;
    });
    html += `</div>`;
    return html;
  }

  function renderTasks(d){
    let rows = d.tasks || [];
    if (filterDisp) rows = rows.filter(r => r.disposition === filterDisp);
    if (filterProv) rows = rows.filter(r => String(r.provider||'') === filterProv);
    const disps = (d.filters && d.filters.dispositions) || [];
    const provs = (d.filters && d.filters.providers) || [];
    let html = `<div class="filters">
      <label class="meta">disposition <select id="fDisp"><option value="">all</option>${disps.map(x=>`<option ${x===filterDisp?'selected':''}>${esc(x)}</option>`).join('')}</select></label>
      <label class="meta">provider <select id="fProv"><option value="">all</option>${provs.map(x=>`<option ${x===filterProv?'selected':''}>${esc(x)}</option>`).join('')}</select></label>
    </div>`;
    if (!rows.length) return html + `<div class="empty">No tasks (decisions.jsonl empty or missing)</div>`;
    html += `<table class="table"><thead><tr>
      <th>When</th><th>Disp</th><th>Action</th><th>Provider</th><th>Bylaw</th><th>Evidence</th>
    </tr></thead><tbody>`;
    rows.forEach((r,i) => {
      html += `<tr data-i="${i}" class="${selected&&selected.id===r.id?'sel':''}">
        <td class="meta">${esc((r.ts||'').slice(0,19))}</td>
        <td><span class="disp ${dispClass(r.disposition)}">${esc(r.disposition)}</span></td>
        <td>${esc(r.action)}</td>
        <td class="meta">${esc(r.provider||'—')}</td>
        <td class="meta">${esc(r.bylaw_action||'—')}</td>
        <td class="meta">${esc(r.evidence_verdict||'—')}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
    setTimeout(() => {
      const fd = document.getElementById('fDisp');
      const fp = document.getElementById('fProv');
      if (fd) fd.onchange = () => { filterDisp = fd.value; render(); };
      if (fp) fp.onchange = () => { filterProv = fp.value; render(); };
      document.querySelectorAll('.table tbody tr').forEach(tr => {
        tr.onclick = () => {
          const i = +tr.getAttribute('data-i');
          selected = rows[i];
          selected.brief_hint = selected.disposition ? 'If a brief was recorded, open /brief for domain view.' : '';
          render();
          renderRail(selected);
        };
      });
    }, 0);
    return html;
  }

  function renderGovernance(d){
    const tabs = ['escalations','bylaws','decisions','pillars'];
    let html = `<div class="tabs">${tabs.map(t=>`<button data-t="${t}" class="${t===govTab?'active':''}">${t}</button>`).join('')}</div>`;
    html += `<div class="note">${esc(d.note||'')}</div>`;
    if (govTab === 'escalations') {
      const rows = d.escalations || [];
      if (!rows.length) html += `<div class="empty">No escalations.jsonl events</div>`;
      rows.forEach(r => {
        html += `<div class="item"><span class="disp ${dispClass(r.status)}">${esc(r.status||r.event)}</span>
          <span class="meta">${esc(r.ts)} · ${esc(r.id)}</span>
          <div>${esc(r.requester)} · ${esc(r.category)} · risk=${esc(r.risk_level)}</div></div>`;
      });
    } else if (govTab === 'bylaws') {
      const rows = d.bylaws || [];
      if (!rows.length) html += `<div class="empty">No bylaws.jsonl</div>`;
      rows.forEach(r => {
        html += `<div class="item"><span class="disp ${dispClass(r.action)}">${esc(r.action)}</span>
          <span class="meta">${esc(r.rule)} · ${esc(r.ts)}</span>
          <div>${esc(r.command)}</div><div class="meta">${esc(r.reason)}</div></div>`;
      });
    } else if (govTab === 'decisions') {
      const rows = d.decisions || [];
      if (!rows.length) html += `<div class="empty">No decisions</div>`;
      rows.forEach(r => {
        html += `<div class="item"><span class="disp ${dispClass(r.disposition)}">${esc(r.disposition)}</span>
          <span class="meta">${esc(r.authorized_by)}</span>
          <div>${esc(r.action)}</div></div>`;
      });
    } else {
      const p = d.pillars || {};
      if (!p.available) html += `<div class="note">${esc(p.note||'Pillars log not present')}</div>`;
      else (p.entries||[]).forEach(e => {
        html += `<div class="item"><pre class="why">${esc(JSON.stringify(e).slice(0,400))}</pre></div>`;
      });
    }
    setTimeout(() => {
      document.querySelectorAll('.tabs button').forEach(b => {
        b.onclick = () => { govTab = b.getAttribute('data-t'); render(); };
      });
    }, 0);
    return html;
  }

  function renderResearch(d){
    let html = `<div class="kpis">${pill('research paid today', d.research_budget_today||0)}
      ${pill('briefs', (d.briefs||[]).length)}
      ${pill('contested', (d.contested_briefs||[]).length)}
      ${pill('weak/flagged', (d.weak_or_flagged||[]).length)}</div>`;
    const o = d.observe || {};
    if (o.available) {
      html += `<h2>Observe last run</h2><div class="meta">verdict=${esc(o.verdict)} actionable=${esc(o.actionable_count)} blocked=${esc(o.non_actionable_count)}</div>`;
      (o.events_sample||[]).forEach(e => {
        html += `<div class="item">${esc(e.title)} <span class="meta">${esc(e.freshness_grade)} · ${e.actionable?'ok':'blocked'}</span></div>`;
      });
    } else html += `<div class="note">No in-memory observe snapshot (run observe while API is up).</div>`;
    html += `<h2>Briefs (quality / contested)</h2>`;
    const briefs = d.briefs || [];
    if (!briefs.length) html += `<div class="empty">No briefs.jsonl</div>`;
    briefs.forEach(b => {
      html += `<div class="item" data-brief="1">
        <span class="disp ${dispClass(b.disposition)}">${esc(b.disposition)}</span>
        <span class="meta">${esc(b.kind)} · band=${esc(b.confidence_band)} · dropped=${esc(b.dropped_count)}</span>
        ${b.contested?'<span class="disp contested">CONTESTED</span>':''}
        <div>${esc(b.question)}</div></div>`;
    });
    return html;
  }

  function renderModels(d){
    const by = d.by_provider || {};
    const keys = Object.keys(by);
    let html = `<div class="kpis">
      ${pill('routes', d.total||0)}
      ${pill('local', d.local_count||0)}
      ${pill('cloud', d.cloud_count||0)}
      ${pill('est. cost Σ', d.estimated_cost_sum||0)}
    </div>`;
    const thr = d.budget_thresholds || {};
    html += `<div class="note">Budget thresholds (config): soft=${esc(thr.soft_budget)} escalate=${esc(thr.escalate_budget)} hard=${esc(thr.hard_ceiling)} · research/day=${esc(thr.research_max_paid_per_day)}</div>`;
    if (!keys.length) html += `<div class="empty">No router.jsonl</div>`;
    else {
      const max = Math.max(...keys.map(k=>by[k]),1);
      keys.forEach(k => {
        html += `<div class="bar"><div class="name">${esc(k)}</div>
          <div class="track"><div class="fill" style="width:${(100*by[k]/max).toFixed(0)}%"></div></div>
          <div class="n">${by[k]}</div></div>`;
      });
    }
    html += `<h2>Why this model</h2>`;
    const why = d.why_this_model || [];
    if (!why.length) html += `<div class="empty">No routing evidence yet</div>`;
    why.forEach((r,i) => {
      html += `<div class="item" data-why="${i}"><b>${esc(r.provider)}</b> · ${esc(r.category)}
        <div class="meta">${esc(r.task_preview)}</div>
        <div class="meta">${esc(r.reason)}</div></div>`;
    });
    setTimeout(() => {
      document.querySelectorAll('[data-why]').forEach(node => {
        node.onclick = () => {
          const i = +node.getAttribute('data-why');
          selected = why[i];
          renderRail(selected);
        };
      });
    }, 0);
    return html;
  }

  function renderAudit(d){
    let html = `<div class="note">${esc(d.redaction_note||'')}</div>`;
    const proj = d.projects || {};
    if (!proj.available) html += `<div class="note">${esc(proj.note||'Projects thin')}</div>`;
    else html += `<h2>Projects (from decisions)</h2><div class="kpis">${Object.keys(proj.projects||{}).map(p=>pill(p, proj.projects[p])).join('')}</div>`;
    html += `<h2>Notifications</h2>`;
    const notes = d.notifications || [];
    if (!notes.length) html += `<div class="empty">No notifications.jsonl</div>`;
    notes.forEach(n => {
      html += `<div class="item"><span class="meta">${esc(n.ts)} · ${esc(n.channel)} · ok=${esc(n.ok)}</span><div>${esc(n.text)}</div></div>`;
    });
    html += `<h2>Brief history</h2>`;
    (d.briefs||[]).forEach(b => {
      html += `<div class="item"><span class="disp ${dispClass(b.disposition)}">${esc(b.disposition)}</span> ${esc(b.kind)} — ${esc(b.question)}</div>`;
    });
    html += `<h2>Recent decisions</h2>`;
    (d.decisions||[]).slice(0,20).forEach(r => {
      html += `<div class="item"><span class="disp ${dispClass(r.disposition)}">${esc(r.disposition)}</span> ${esc(r.action)}</div>`;
    });
    return html;
  }

  function render(){
    const d = cache[screen] || {};
    const center = el('center');
    let html = '';
    if (d.error) html = `<div class="empty">Error: ${esc(d.error)}</div>`;
    else if (screen==='overview') html = renderOverview(d);
    else if (screen==='tasks') html = renderTasks(d);
    else if (screen==='governance') html = renderGovernance(d);
    else if (screen==='research') html = renderResearch(d);
    else if (screen==='models') html = renderModels(d);
    else if (screen==='audit') html = renderAudit(d);
    else html = `<div class="empty">Unknown screen</div>`;
    if ((d.missing_logs||[]).length) {
      html = `<div class="note">Missing logs: ${esc((d.missing_logs||[]).join(', '))}</div>` + html;
    }
    center.innerHTML = html;
    if (selected) renderRail(selected);
  }

  async function tick(){
    const conn = el('conn');
    try {
      const r = await fetch('/console/data?screen='+encodeURIComponent(screen)+'&limit=60', {cache:'no-store'});
      if (!r.ok) throw new Error('HTTP '+r.status);
      const data = await r.json();
      cache[screen] = data;
      lastOk = Date.now();
      conn.textContent = 'live · ' + screen + ' · ' + (data.ts||'').toString().slice(11,19) + 'Z';
      conn.className = 'status live';
      render();
    } catch (e) {
      conn.textContent = 'error · ' + (e.message||'fetch');
      conn.className = 'status err';
    }
  }
  setInterval(() => {
    if (lastOk && Date.now()-lastOk > 25000) {
      const c = el('conn');
      if (!c.className.includes('err')) { c.className='status stale'; c.textContent='stale · retrying'; }
    }
  }, 3000);
  tick();
  setInterval(tick, 10000);
})();
</script>
</body>
</html>
"""
