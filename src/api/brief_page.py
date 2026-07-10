"""Self-contained governed-brief HTML — no CDN, no external assets. READ-ONLY."""

BRIEF_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AgentGRIT Brief · read-only</title>
<style>
:root {
  --bg:#0f1218; --panel:#171b24; --border:#2a3140; --text:#e6eaf2; --muted:#8b93a7;
  --proceed:#3ecf8e; --refused:#f07178; --escalated:#e6b450; --contested:#c792ea;
  --unknown:#6b7280; --accent:#5b9fd4; --strong:#3ecf8e; --adequate:#5b9fd4; --thin:#e6b450; --flagged:#c792ea;
}
* { box-sizing:border-box; }
body { margin:0; font:14px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif;
  background:var(--bg); color:var(--text); }
header { position:sticky; top:0; z-index:5; background:#0c0f14f2;
  border-bottom:1px solid var(--border); padding:12px 18px;
  display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
header h1 { font-size:15px; margin:0; font-weight:600; }
.badge { font-size:11px; color:var(--muted); border:1px solid var(--border);
  border-radius:999px; padding:2px 8px; }
header .status { margin-left:auto; font-size:11px; color:var(--muted); }
header .status.live { color:var(--proceed); }
header .status.err { color:var(--refused); }
.disclaimer-bar { width:100%; font-size:12px; color:var(--muted); margin-top:4px; }
main { max-width:720px; margin:0 auto; padding:18px 16px 40px; }
.card { background:var(--panel); border:1px solid var(--border); border-radius:10px;
  padding:16px 18px; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }
.disp { font-size:11px; font-weight:700; letter-spacing:.04em; padding:2px 8px;
  border-radius:4px; }
.disp.proceed { background:#143528; color:var(--proceed); }
.disp.refused { background:#3a1a1e; color:var(--refused); }
.disp.escalated { background:#3a3014; color:var(--escalated); }
.disp.contested { background:#2a1f3a; color:var(--contested); }
.disp.unknown { background:#222; color:var(--unknown); }
.meta { color:var(--muted); font-size:12px; }
h2 { font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:16px 0 8px; font-weight:600; }
.question { font-size:16px; font-weight:600; margin:4px 0 12px; word-break:break-word; }
.meter { margin:8px 0 4px; }
.meter-label { display:flex; justify-content:space-between; font-size:12px; color:var(--muted); }
.track { height:10px; background:#0f1218; border-radius:5px; overflow:hidden; margin-top:4px; }
.fill { height:100%; border-radius:5px; }
.fill.strong { background:var(--strong); }
.fill.adequate { background:var(--adequate); }
.fill.thin { background:var(--thin); }
.fill.flagged { background:var(--flagged); }
.banner { border:1px solid var(--contested); background:#221833; color:var(--contested);
  border-radius:6px; padding:10px 12px; margin:12px 0; font-size:13px; }
.auth { border-top:1px solid var(--border); padding:10px 0; }
.auth:first-of-type { border-top:0; }
.auth a { color:var(--accent); word-break:break-all; }
.auth .cite { color:var(--muted); font-size:12px; }
.needs li { margin:4px 0; }
.empty { color:var(--muted); font-style:italic; padding:12px 0; }
select { background:#0f1218; color:var(--text); border:1px solid var(--border);
  border-radius:4px; padding:4px 8px; font-size:12px; }
footer { max-width:720px; margin:0 auto; padding:8px 16px 24px; font-size:11px;
  color:var(--muted); text-align:center; }
</style>
</head>
<body>
<header>
  <h1 id="title">Governed brief</h1>
  <span class="badge">READ-ONLY · verified citations only</span>
  <label class="meta">profile
    <select id="profile">
      <option value="generic">generic</option>
      <option value="legal">legal (sample)</option>
    </select>
  </label>
  <label class="meta">run
    <select id="run"><option value="latest">latest</option></select>
  </label>
  <span class="status" id="conn">loading…</span>
  <div class="disclaimer-bar" id="disclaimer-top"></div>
</header>
<main>
  <div class="card" id="card">
    <div class="empty">Loading brief…</div>
  </div>
</main>
<footer id="disclaimer-foot"></footer>
<script>
(function(){
  const params = new URLSearchParams(location.search);
  const el = id => document.getElementById(id);
  if (params.get('profile')) el('profile').value = params.get('profile');
  if (params.get('run')) { /* option added after list loads */ }

  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }
  function dispClass(d){
    d = (d||'unknown').toLowerCase();
    if (['proceed','refused','escalated','contested'].indexOf(d)>=0) return d;
    if (d === 'refused_upl') return 'refused';
    return 'unknown';
  }
  function bandPct(band, score){
    if (band === 'flagged') return 100;
    if (score == null || isNaN(score)) {
      return band === 'strong' ? 90 : band === 'adequate' ? 70 : 40;
    }
    return Math.max(5, Math.min(100, Math.round(Number(score)*100)));
  }
  function render(data){
    const prof = data.profile || {};
    el('title').textContent = prof.title || 'Governed brief';
    const disc = prof.disclaimer || '';
    el('disclaimer-top').textContent = disc;
    el('disclaimer-foot').textContent = disc + ' · UI never acts · unverified URLs never shown';

    if (data.empty) {
      el('card').innerHTML = `<div class="empty">${esc(data.message || 'No briefs yet.')}</div>`;
      return;
    }
    const band = data.confidence_band || 'thin';
    const score = data.confidence_score;
    const scoreLabel = score == null ? '—' : Number(score).toFixed(2);
    const authorities = (data.authorities || []).filter(a => a && a.verified && a.url);
    let html = `
      <div class="row">
        <span class="disp ${dispClass(data.disposition)}">${esc(String(data.disposition||'unknown').toUpperCase())}</span>
        <span class="meta">kind=${esc(data.kind)} · gate=${esc(data.autonomy_gate||'—')} · ${esc(data.provider||'')}</span>
        <span class="meta" style="margin-left:auto">${esc(data.ts||'')}</span>
      </div>
      <div class="question">${esc(data.question)}</div>
      <div class="meter">
        <div class="meter-label">
          <span>confidence · <b style="color:var(--text)">${esc(band)}</b></span>
          <span>score ${esc(scoreLabel)}${data.evidence_verdict ? ' · verdict '+esc(data.evidence_verdict) : ''}</span>
        </div>
        <div class="track"><div class="fill ${esc(band)}" style="width:${bandPct(band, score)}%"></div></div>
      </div>`;
    if (data.contested) {
      html += `<div class="banner"><strong>${esc(prof.contested_label||'CONTESTED')}</strong><br/>${esc(data.contested_reason||'Sources disagree — do not treat as corroboration.')}</div>`;
    }
    html += `<h2>Authorities <span class="meta">(verified only · dropped=${esc(data.dropped_count||0)})</span></h2>`;
    if (!authorities.length) {
      html += `<div class="empty">No verified citations. Dropped/uncited claims are not shown as authorities.</div>`;
    } else {
      authorities.forEach((a,i) => {
        html += `<div class="auth">
          <div><b>${i+1}. ${esc(a.title)}</b></div>
          ${a.citation ? `<div class="cite">${esc(a.citation)}</div>` : ''}
          <div><a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.url)}</a></div>
        </div>`;
      });
    }
    const needs = data.needs_judgment || [];
    html += `<h2>${esc(prof.judgment_label||'Needs human judgment')}</h2>`;
    if (!needs.length) {
      html += `<div class="empty">None listed.</div>`;
    } else {
      html += `<ul class="needs">${needs.map(n => `<li>${esc(n)}</li>`).join('')}</ul>`;
    }
    el('card').innerHTML = html;
  }
  async function loadList(){
    try {
      const r = await fetch('/brief/data?list=1', {cache:'no-store'});
      if (!r.ok) return;
      const data = await r.json();
      const sel = el('run');
      const cur = params.get('run') || 'latest';
      sel.innerHTML = '<option value="latest">latest</option>';
      (data.runs || []).forEach(x => {
        const opt = document.createElement('option');
        opt.value = x.id;
        opt.textContent = (x.kind||'') + ' · ' + (x.question||x.id||'').slice(0,40);
        if (x.id === cur) opt.selected = true;
        sel.appendChild(opt);
      });
      if (cur && cur !== 'latest') sel.value = cur;
    } catch (e) {}
  }
  async function tick(){
    const conn = el('conn');
    const profile = el('profile').value || 'generic';
    const run = el('run').value || 'latest';
    try {
      const r = await fetch('/brief/data?run='+encodeURIComponent(run)+'&profile='+encodeURIComponent(profile), {cache:'no-store'});
      if (!r.ok) throw new Error('HTTP '+r.status);
      const data = await r.json();
      render(data);
      conn.textContent = 'live · ' + (data.ts||'').toString().slice(11,19);
      conn.className = 'status live';
    } catch (e) {
      conn.textContent = 'error';
      conn.className = 'status err';
    }
  }
  el('profile').addEventListener('change', tick);
  el('run').addEventListener('change', tick);
  loadList().then(tick);
  setInterval(tick, 15000);
})();
</script>
</body>
</html>
"""
