"""Multi-screen operator console HTML — self-contained, no CDN. READ-ONLY.

Product-grade polish (v0.2.5): typography 14px, 4/8/12/16 spacing, overview
mission-control cards, labeled context rail, clearer tabs/filters.
Behavior and data contracts unchanged — CONSOLE_HTML only.
"""

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
  --nav-w:176px; --rail-w:300px;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px;
  --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --r:8px;
}
* { box-sizing:border-box; }
body {
  margin:0;
  font:14px/1.5 var(--font);
  background:var(--bg); color:var(--text);
  height:100vh; display:flex; flex-direction:column;
}
/* Type scale */
.h1 { font-size:16px; font-weight:650; letter-spacing:.01em; margin:0; }
.h2 { font-size:11px; font-weight:650; letter-spacing:.07em; text-transform:uppercase;
  color:var(--muted); margin:0 0 var(--s2); }
.h3 { font-size:11px; font-weight:650; letter-spacing:.06em; text-transform:uppercase;
  color:var(--muted); margin:0 0 var(--s1); }
body h2 { font-size:11px; font-weight:650; letter-spacing:.07em; text-transform:uppercase;
  color:var(--muted); margin:var(--s4) 0 var(--s2); }

header.top {
  display:flex; align-items:center; gap:var(--s3); padding:var(--s3) var(--s4);
  border-bottom:1px solid var(--border); background:#0a0c10f2; flex-shrink:0;
}
.badge {
  font-size:11px; color:var(--muted); border:1px solid var(--border);
  border-radius:999px; padding:var(--s1) var(--s2);
}
.badge.warn { border-color:var(--escalated); color:var(--escalated); }
header .status { margin-left:auto; font-size:12px; color:var(--muted); }
header .status.live { color:var(--proceed); }
header .status.err { color:var(--refused); }
header .status.stale { color:var(--escalated); }

.shell { display:flex; flex:1; min-height:0; }
nav.side {
  width:var(--nav-w); border-right:1px solid var(--border); background:var(--panel);
  padding:var(--s2) 0; flex-shrink:0; overflow:auto;
}
nav.side button {
  display:block; width:100%; text-align:left; background:transparent;
  border:0; border-left:2px solid transparent; color:var(--muted);
  padding:var(--s2) var(--s3); font:inherit; cursor:pointer;
  transition: background .12s, color .12s;
}
nav.side button:hover { color:var(--text); background:#1c2230; }
nav.side button.active {
  color:var(--text); background:#1e2533; border-left-color:var(--accent); font-weight:600;
}
nav.side .hint {
  padding:var(--s4) var(--s3); font-size:11px; color:var(--muted); line-height:1.45;
  border-top:1px solid var(--border); margin-top:var(--s2);
}

.center { flex:1; overflow:auto; padding:var(--s4); min-width:0; }
.rail {
  width:var(--rail-w); border-left:1px solid var(--border); background:var(--panel);
  padding:var(--s4); overflow:auto; flex-shrink:0;
}
@media (max-width:960px) {
  .rail { display:none; }
  nav.side { width:132px; }
}

/* Overview mission-control cards */
.mc-grid {
  display:grid;
  grid-template-columns:repeat(4, minmax(0,1fr));
  gap:var(--s3);
  margin-bottom:var(--s4);
}
@media (max-width:1100px) { .mc-grid { grid-template-columns:repeat(2, minmax(0,1fr)); } }
@media (max-width:640px) { .mc-grid { grid-template-columns:1fr; } }
.mc-card {
  background:var(--panel); border:1px solid var(--border); border-radius:var(--r);
  padding:var(--s3) var(--s4); min-height:96px;
  display:flex; flex-direction:column; gap:var(--s2);
}
.mc-card .mc-title {
  font-size:11px; font-weight:650; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted);
}
.mc-card .mc-value {
  font-size:28px; font-weight:700; letter-spacing:-.02em; line-height:1.1;
}
.mc-card .mc-sub { font-size:12px; color:var(--muted); line-height:1.4; }
.mc-card.accent-border { border-color:#2a3a4a; }
.mc-card.block-card .mc-value { font-size:13px; font-weight:600; letter-spacing:0; color:var(--refused); }
.mc-chips { display:flex; flex-wrap:wrap; gap:var(--s1); margin-top:var(--s1); }
.chip {
  font-size:11px; padding:2px 8px; border-radius:999px;
  background:var(--panel2); color:var(--muted); border:1px solid var(--border);
}
.chip b { color:var(--text); font-weight:600; }

.kpis { display:flex; flex-wrap:wrap; gap:var(--s2); margin-bottom:var(--s3); }
.kpi {
  background:var(--panel); border:1px solid var(--border); border-radius:var(--r);
  padding:var(--s2) var(--s3); min-width:100px;
}
.kpi .v { font-size:18px; font-weight:650; }
.kpi .l { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; margin-top:2px; }

.table { width:100%; border-collapse:collapse; font-size:13px; }
.table th {
  text-align:left; color:var(--muted); font-weight:650; font-size:10px;
  text-transform:uppercase; letter-spacing:.05em;
  padding:var(--s2) var(--s2); border-bottom:1px solid var(--border);
}
.table td { padding:var(--s2); border-bottom:1px solid var(--border); vertical-align:top; }
.table tr { cursor:pointer; transition: background .1s; }
.table tr:hover { background:#1c2230; }
.table tr.sel { background:#222a38; outline:1px solid #334055; }

.disp {
  font-size:10px; font-weight:700; letter-spacing:.04em; padding:2px 7px; border-radius:4px;
  display:inline-block;
}
.disp.proceed { background:#143528; color:var(--proceed); }
.disp.refused { background:#3a1a1e; color:var(--refused); }
.disp.escalated { background:#3a3014; color:var(--escalated); }
.disp.contested { background:#2a1f3a; color:var(--contested); }
.disp.unknown,.disp.pending { background:#222; color:var(--muted); }

.meta { color:var(--muted); font-size:12px; }
.item { border-bottom:1px solid var(--border); padding:var(--s2) 0; }
.empty { color:var(--muted); font-style:italic; padding:var(--s3) var(--s1); }

/* Tabs — clear selected state */
.tabs { display:flex; gap:var(--s2); margin-bottom:var(--s3); flex-wrap:wrap; }
.tabs button {
  background:transparent; border:1px solid var(--border); color:var(--muted);
  border-radius:6px; padding:var(--s2) var(--s3); font:inherit; cursor:pointer;
  transition: background .12s, color .12s, border-color .12s;
}
.tabs button:hover { color:var(--text); border-color:#3a4558; }
.tabs button.active {
  color:var(--text); background:#1e2a3a; border-color:var(--accent);
  box-shadow: inset 0 -2px 0 var(--accent); font-weight:600;
}

.bar { display:flex; align-items:center; gap:var(--s2); margin:var(--s1) 0; }
.bar .name { width:96px; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px; }
.bar .track { flex:1; height:8px; background:#0f1218; border-radius:4px; overflow:hidden; }
.bar .fill { height:100%; background:var(--accent); }
.bar .n { width:36px; text-align:right; color:var(--muted); font-size:12px; }

.note {
  font-size:12px; color:var(--muted); border:1px dashed var(--border); border-radius:var(--r);
  padding:var(--s2) var(--s3); margin:var(--s2) 0 var(--s3);
  background:#12161e;
}

/* Filters */
.filters {
  display:flex; gap:var(--s3); margin-bottom:var(--s3); flex-wrap:wrap; align-items:center;
  padding:var(--s2) var(--s3); background:var(--panel); border:1px solid var(--border);
  border-radius:var(--r);
}
.filters label { display:flex; align-items:center; gap:var(--s2); font-size:12px; color:var(--muted); }
.filters select {
  background:#0f1218; color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:var(--s1) var(--s2); font:inherit; min-width:120px;
}
.filters select:focus { outline:1px solid var(--accent); border-color:var(--accent); }

.timeline .item { padding:var(--s2) 0; }
.timeline .item .kind {
  font-size:10px; color:var(--accent); text-transform:uppercase; letter-spacing:.05em;
  font-weight:650; margin-right:var(--s2);
}

/* Log / reason blocks */
pre.why, .logblock {
  white-space:pre-wrap; word-break:break-word;
  font-family:var(--mono); font-size:11.5px; line-height:1.45;
  color:#b8c0d0; background:#0a0d12;
  border:1px solid #1e2533; border-radius:6px;
  padding:var(--s2) var(--s3); max-height:220px; overflow:auto; margin:0;
}

/* Context rail sections */
.rail-sec { margin-bottom:var(--s4); }
.rail-sec .h3 { margin-bottom:var(--s2); color:var(--muted); }
.rail-sec .body { font-size:13px; font-weight:500; }
.rail .h2 { margin-bottom:var(--s3); }
.section-card {
  background:var(--panel); border:1px solid var(--border); border-radius:var(--r);
  padding:var(--s3) var(--s4); margin-bottom:var(--s3);
}
</style>
</head>
<body>
<header class="top">
  <h1 class="h1">AgentGRIT Ops</h1>
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
    <div class="h2">Context</div>
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
  function chip(k,v){ return `<span class="chip">${esc(k)}: <b>${esc(v)}</b></span>`; }
  function railSec(title, bodyHtml){
    return `<div class="rail-sec"><div class="h3">${esc(title)}</div><div class="body">${bodyHtml}</div></div>`;
  }

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
    if (row.action || row.question || row.task_preview) {
      html += railSec('Task', `<div style="font-weight:600">${esc(row.action||row.question||row.task_preview)}</div>`);
    }
    if (row.disposition) {
      html += railSec('Disposition',
        `<span class="disp ${dispClass(row.disposition)}">${esc(row.disposition).toUpperCase()}</span>`);
    }
    if (row.provider) {
      html += railSec('Provider', esc(row.provider) + (row.category ? ` <span class="meta">· ${esc(row.category)}</span>` : ''));
    }
    if (row.bylaw_action) {
      html += railSec('Bylaw',
        `<div>${esc(row.bylaw_action)}</div>` +
        (row.bylaw_reason ? `<pre class="logblock" style="margin-top:8px">${esc(row.bylaw_reason)}</pre>` : ''));
    }
    if (row.evidence_verdict != null && row.evidence_verdict !== '') {
      html += railSec('Evidence',
        `${esc(row.evidence_verdict)}` +
        (row.evidence_score!=null ? ` <span class="meta">score=${esc(row.evidence_score)}</span>` : '') +
        (row.evidence_require_human ? ` <span class="disp escalated">human</span>` : ''));
    }
    if (row.route_reason || row.reason) {
      html += railSec('Route reason',
        `<pre class="logblock">${esc(row.route_reason||row.reason||'')}</pre>`);
    }
    if (row.rationale) {
      html += railSec('Rationale', `<pre class="logblock">${esc(row.rationale)}</pre>`);
    }
    if (row.authorized_by) {
      html += railSec('Authorized by', esc(row.authorized_by));
    }
    if (row.confidence_band || row.autonomy_gate) {
      html += railSec('Brief',
        `${esc(row.confidence_band||'—')}` +
        (row.autonomy_gate ? ` <span class="meta">· gate=${esc(row.autonomy_gate)}</span>` : ''));
    }
    if (row.brief_hint) {
      html += `<div class="note">${esc(row.brief_hint)}</div>`;
    }
    html += `<div class="note">Domain brief UI: <code>/brief</code> (read-only). Approvals: CLI / Telegram only.</div>`;
    body.innerHTML = html || '<div class="empty">No detail fields.</div>';
  }

  function renderOverview(d){
    const k = d.kpis || {};
    const disp = k.dispositions_today || {};
    const dispChips = Object.keys(disp).map(x => chip(x, disp[x])).join('') ||
      '<span class="meta">No dispositions today</span>';
    const trustLine = `↑ ${esc(k.trust_promotions||0)}  ·  ↓ ${esc(k.trust_demotions||0)}`;
    const blocked = k.last_blocked;
    let html = `<div class="mc-grid">
      <div class="mc-card accent-border">
        <div class="mc-title">Today</div>
        <div class="mc-value">${esc(k.decisions_today||0)}</div>
        <div class="mc-sub">decisions · ${esc(k.pending_escalations||0)} pending escalations</div>
        <div class="mc-chips">${dispChips}</div>
      </div>
      <div class="mc-card">
        <div class="mc-title">Trust</div>
        <div class="mc-value" style="font-size:20px">${trustLine}</div>
        <div class="mc-sub">promotions · demotions (recent)</div>
      </div>
      <div class="mc-card">
        <div class="mc-title">Router totals</div>
        <div class="mc-value">${esc(k.router_total||0)}</div>
        <div class="mc-sub">routes · est. cost Σ ${esc(
          (k.router_cost_sum||0).toPrecision ? Number(k.router_cost_sum||0).toPrecision(3) : 0
        )}</div>
      </div>
      <div class="mc-card block-card">
        <div class="mc-title">Last blocked</div>
        <div class="mc-value">${blocked ? esc((blocked.action||'').slice(0,72)) : '—'}</div>
        <div class="mc-sub">${blocked ? esc((blocked.reason||'').slice(0,100)) : 'No blocked actions in tail'}</div>
      </div>
    </div>`;

    const agents = k.active_agent_hints || {};
    if (Object.keys(agents).length) {
      html += `<h2>Agent hints <span class="meta">(from authorized_by)</span></h2>
        <div class="kpis">${Object.keys(agents).map(a=>pill(a, agents[a])).join('')}</div>`;
    } else {
      html += `<div class="note">Active-agent count is inferred from recent authorized_by tags — no dedicated agent process log.</div>`;
    }
    html += `<h2>Recent activity</h2><div class="timeline section-card" style="padding-top:4px;padding-bottom:4px">`;
    const tl = d.timeline || [];
    if (!tl.length) html += `<div class="empty">No recent activity</div>`;
    tl.forEach(t => {
      html += `<div class="item"><span class="kind">${esc(t.kind)}</span>
        <span class="disp ${dispClass(t.label)}">${esc(t.label)}</span>
        <span class="meta">${esc(t.ts)}</span>
        <div style="margin-top:4px">${esc(t.text)}</div></div>`;
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
      <label>Disposition
        <select id="fDisp"><option value="">All</option>${disps.map(x=>`<option ${x===filterDisp?'selected':''} value="${esc(x)}">${esc(x)}</option>`).join('')}</select>
      </label>
      <label>Provider
        <select id="fProv"><option value="">All</option>${provs.map(x=>`<option ${x===filterProv?'selected':''} value="${esc(x)}">${esc(x)}</option>`).join('')}</select>
      </label>
      <span class="meta" style="margin-left:auto">${rows.length} rows</span>
    </div>`;
    if (!rows.length) return html + `<div class="empty">No tasks (decisions.jsonl empty or missing)</div>`;
    html += `<div class="section-card" style="padding:0;overflow:auto"><table class="table"><thead><tr>
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
    html += `</tbody></table></div>`;
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
          <div style="margin-top:4px">${esc(r.requester)} · ${esc(r.category)} · risk=${esc(r.risk_level)}</div></div>`;
      });
    } else if (govTab === 'bylaws') {
      const rows = d.bylaws || [];
      if (!rows.length) html += `<div class="empty">No bylaws.jsonl</div>`;
      rows.forEach(r => {
        html += `<div class="item"><span class="disp ${dispClass(r.action)}">${esc(r.action)}</span>
          <span class="meta">${esc(r.rule)} · ${esc(r.ts)}</span>
          <div style="margin-top:4px">${esc(r.command)}</div>
          <pre class="logblock" style="margin-top:8px">${esc(r.reason)}</pre></div>`;
      });
    } else if (govTab === 'decisions') {
      const rows = d.decisions || [];
      if (!rows.length) html += `<div class="empty">No decisions</div>`;
      rows.forEach(r => {
        html += `<div class="item"><span class="disp ${dispClass(r.disposition)}">${esc(r.disposition)}</span>
          <span class="meta">${esc(r.authorized_by)}</span>
          <div style="margin-top:4px">${esc(r.action)}</div></div>`;
      });
    } else {
      const p = d.pillars || {};
      if (!p.available) html += `<div class="note">${esc(p.note||'Pillars log not present')}</div>`;
      else (p.entries||[]).forEach(e => {
        html += `<div class="item"><pre class="logblock">${esc(JSON.stringify(e).slice(0,400))}</pre></div>`;
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
      html += `<h2>Observe last run</h2>
        <div class="section-card meta">verdict=${esc(o.verdict)} · actionable=${esc(o.actionable_count)} · blocked=${esc(o.non_actionable_count)}</div>`;
      (o.events_sample||[]).forEach(e => {
        html += `<div class="item">${esc(e.title)} <span class="meta">${esc(e.freshness_grade)} · ${e.actionable?'ok':'blocked'}</span></div>`;
      });
    } else html += `<div class="note">No in-memory observe snapshot (run observe while API is up).</div>`;
    html += `<h2>Briefs (quality / contested)</h2>`;
    const briefs = d.briefs || [];
    if (!briefs.length) html += `<div class="empty">No briefs.jsonl</div>`;
    briefs.forEach(b => {
      html += `<div class="item">
        <span class="disp ${dispClass(b.disposition)}">${esc(b.disposition)}</span>
        <span class="meta">${esc(b.kind)} · band=${esc(b.confidence_band)} · dropped=${esc(b.dropped_count)}</span>
        ${b.contested?'<span class="disp contested">CONTESTED</span>':''}
        <div style="margin-top:4px">${esc(b.question)}</div></div>`;
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
    html += `<div class="note">Budget thresholds (config): soft=${esc(thr.soft_budget)} · escalate=${esc(thr.escalate_budget)} · hard=${esc(thr.hard_ceiling)} · research/day=${esc(thr.research_max_paid_per_day)}</div>`;
    if (!keys.length) html += `<div class="empty">No router.jsonl</div>`;
    else {
      const max = Math.max(...keys.map(k=>by[k]),1);
      html += `<div class="section-card">`;
      keys.forEach(k => {
        html += `<div class="bar"><div class="name">${esc(k)}</div>
          <div class="track"><div class="fill" style="width:${(100*by[k]/max).toFixed(0)}%"></div></div>
          <div class="n">${by[k]}</div></div>`;
      });
      html += `</div>`;
    }
    html += `<h2>Why this model</h2>`;
    const why = d.why_this_model || [];
    if (!why.length) html += `<div class="empty">No routing evidence yet</div>`;
    why.forEach((r,i) => {
      html += `<div class="item" data-why="${i}" style="cursor:pointer">
        <b>${esc(r.provider)}</b> · <span class="meta">${esc(r.category)}</span>
        <div class="meta" style="margin-top:4px">${esc(r.task_preview)}</div>
        <pre class="logblock" style="margin-top:8px">${esc(r.reason)}</pre></div>`;
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
      html += `<div class="item"><span class="meta">${esc(n.ts)} · ${esc(n.channel)} · ok=${esc(n.ok)}</span><div style="margin-top:4px">${esc(n.text)}</div></div>`;
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
