#!/usr/bin/env python3
"""
AgentGRIT HUD -- a live dashboard for everything the governance runtime is doing.

Zero dependencies (stdlib only). Reads the JSONL logs the GM/observer already
write, plus Ollama status and local system usage, and serves a single-page HUD
that auto-refreshes. Shows: GM status, per-project activity, the escalation feed
(JR -> Manager -> Pillar briefs awaiting your call), the research knowledge base
+ daily budget, recent notifications, self-improvement lessons, the local model
roster, and CPU / memory / load.

Run:   python3 scripts/dashboard.py         # then open http://localhost:8787
       make hud
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
PORT = int(os.environ.get("HUD_PORT", "8787"))


def _tail_jsonl(name: str, n: int = 50) -> list:
    p = LOGS / name
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text().splitlines()[-n:]:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _gm_running() -> bool:
    pid_f = LOGS / "gm.pid"
    if not pid_f.exists():
        return False
    try:
        os.kill(int(pid_f.read_text().strip()), 0)
        return True
    except Exception:
        return False


def _ollama_models() -> list:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        return [{"name": m.get("name"), "size_gb": round(m.get("size", 0) / 1e9, 1)}
                for m in data.get("models", [])]
    except Exception:
        return []


def _system() -> dict:
    s = {"load": None, "mem_used_pct": None, "cpu_pct": None}
    try:
        s["load"] = [round(x, 2) for x in os.getloadavg()]
    except Exception:
        pass
    try:  # macOS memory pressure
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            if "free percentage" in line.lower():
                free = int("".join(c for c in line if c.isdigit()))
                s["mem_used_pct"] = 100 - free
    except Exception:
        pass
    try:  # cpu via top snapshot (mac)
        out = subprocess.run(["top", "-l", "1", "-n", "0"], capture_output=True, text=True, timeout=4).stdout
        for line in out.splitlines():
            if line.startswith("CPU usage"):
                # "CPU usage: 8.11% user, 12.9% sys, 78.9% idle"
                idle = float(line.split(",")[-1].strip().split("%")[0])
                s["cpu_pct"] = round(100 - idle, 1)
    except Exception:
        pass
    return s


def _state() -> dict:
    hb = _tail_jsonl("heartbeat.jsonl", 200)
    pending = _tail_jsonl("pending.jsonl", 40)
    resolved = _tail_jsonl("resolved.jsonl", 40)
    notes = _tail_jsonl("notifications.jsonl", 40)
    knowledge = _tail_jsonl("knowledge.jsonl", 40)
    lessons = _tail_jsonl("lessons.jsonl", 20)
    budget = _tail_jsonl("research_budget.jsonl", 200)

    # aggregate per-project from heartbeats
    projects: dict[str, dict] = {}
    for h in hb:
        pj = (h.get("router") or {}).get("project") or h.get("project") or "—"
        projects.setdefault(pj, {"cycles": 0, "last_provider": "—", "last": ""})
    # newer GM logs project inside the printed line only; fall back to pending
    for e in pending:
        pj = e.get("project", "—")
        projects.setdefault(pj, {"cycles": 0, "last_provider": "—", "last": ""})
        projects[pj]["escalations"] = projects[pj].get("escalations", 0) + 1

    today = date.today().isoformat()
    paid_today = sum(1 for b in budget if b.get("date") == today)

    return {
        "ts": datetime.now().isoformat(),
        "gm_running": _gm_running(),
        "projects": projects,
        "pending": list(reversed(pending))[:12],
        "resolved": list(reversed(resolved))[:8],
        "notifications": list(reversed(notes))[:15],
        "knowledge": list(reversed(knowledge))[:12],
        "lessons": list(reversed(lessons))[:6],
        "knowledge_count": len(knowledge),
        "paid_research_today": paid_today,
        "ollama": _ollama_models(),
        "system": _system(),
        "heartbeats": len(hb),
    }


HTML = """<!doctype html><html><head><meta charset=utf-8>
<title>AgentGRIT HUD</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0e14;--card:#131824;--line:#222b3d;--txt:#c9d4e5;--dim:#7488a5;--ok:#3ddc84;--warn:#ffb02e;--bad:#ff5c68;--acc:#5b9dff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:14px 20px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
h1{font-size:15px;margin:0;letter-spacing:.5px}.pill{padding:2px 10px;border-radius:20px;font-size:11px;font-weight:600}
.on{background:rgba(61,220,132,.15);color:var(--ok)}.off{background:rgba(255,92,104,.15);color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;padding:16px 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin:0 0 10px}
.row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.03);gap:8px}
.row:last-child{border:0}.k{color:var(--dim)}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.tag{font-size:10px;padding:1px 7px;border-radius:5px;background:rgba(91,157,255,.14);color:var(--acc)}
.esc{background:rgba(255,176,46,.08);border-left:3px solid var(--warn);padding:8px 10px;border-radius:5px;margin-bottom:8px;font-size:12px}
.small{font-size:11px;color:var(--dim)}.bar{height:6px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:4px}
.bar>i{display:block;height:100%;background:var(--acc)}
.feed div{padding:4px 0;border-bottom:1px solid rgba(255,255,255,.03);font-size:12px}
.big{font-size:26px;font-weight:700}.muted{color:var(--dim)}
</style></head><body>
<header><h1>⬡ AgentGRIT HUD</h1><span id=gm class=pill>…</span>
<span class=small id=meta></span><span class=small style="margin-left:auto" id=clock></span></header>
<div class=grid id=grid></div>
<script>
function el(t,c,h){var e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e}
function card(title,body){var c=el('div','card');c.appendChild(el('h2',null,title));c.appendChild(body);return c}
function rows(pairs){var d=el('div');pairs.forEach(function(p){var r=el('div','row');r.appendChild(el('span','k',p[0]));r.appendChild(el('span','mono',p[1]));d.appendChild(r)});return d}
async function tick(){
 let s;try{s=await (await fetch('/api/state')).json()}catch(e){return}
 var gm=document.getElementById('gm');gm.textContent=s.gm_running?'GM ONLINE':'GM OFFLINE';gm.className='pill '+(s.gm_running?'on':'off');
 document.getElementById('meta').textContent=Object.keys(s.projects).length+' projects · '+s.heartbeats+' heartbeats · '+s.knowledge_count+' knowledge';
 document.getElementById('clock').textContent=new Date(s.ts).toLocaleTimeString();
 var g=document.getElementById('grid');g.innerHTML='';
 // system
 var sy=s.system,sb=el('div');
 sb.appendChild(rows([['CPU',(sy.cpu_pct!=null?sy.cpu_pct+'%':'—')],['Memory used',(sy.mem_used_pct!=null?sy.mem_used_pct+'%':'—')],['Load avg',(sy.load?sy.load.join(' '):'—')],['Paid research today',s.paid_research_today]]));
 g.appendChild(card('System',sb));
 // ollama
 var ob=el('div');if(s.ollama.length){s.ollama.forEach(function(m){var r=el('div','row');r.appendChild(el('span','mono',m.name));r.appendChild(el('span','small',m.size_gb+' GB'));ob.appendChild(r)})}else ob.appendChild(el('div','muted','Ollama not reachable'));
 g.appendChild(card('Local models (Ollama)',ob));
 // projects
 var pb=el('div');var pk=Object.keys(s.projects);if(pk.length){pk.forEach(function(k){var p=s.projects[k];var r=el('div','row');r.appendChild(el('span','mono',k));r.appendChild(el('span','small',(p.escalations||0)+' esc'));pb.appendChild(r)})}else pb.appendChild(el('div','muted','No project activity yet'));
 g.appendChild(card('Projects watched ('+pk.length+')',pb));
 // escalations
 var eb=el('div');if(s.pending.length){s.pending.forEach(function(e){var d=el('div','esc');var dl=(e.deliberation||{});d.innerHTML='<b>'+(e.project||'—')+'</b> · '+(e.action||'')+'<div class=small>Manager: '+((dl.verdict||'—')+'').toUpperCase()+' · '+new Date(e.ts).toLocaleTimeString()+'</div>';eb.appendChild(d)})}else eb.appendChild(el('div','muted','No pending escalations — all clear'));
 g.appendChild(card('Escalations awaiting you',eb));
 // knowledge
 var kb=el('div','feed');if(s.knowledge.length){s.knowledge.forEach(function(k){kb.appendChild(el('div',null,'<span class=tag>'+(k.provider||'?')+'</span> '+(k.query||'').slice(0,70)))})}else kb.appendChild(el('div','muted','No research yet'));
 g.appendChild(card('Research knowledge base',kb));
 // notifications
 var nb=el('div','feed');if(s.notifications.length){s.notifications.forEach(function(n){nb.appendChild(el('div',null,(n.text||'').slice(0,90)))})}else nb.appendChild(el('div','muted','No notifications'));
 g.appendChild(card('Notifications',nb));
 // lessons
 var lb=el('div','feed');if(s.lessons.length){s.lessons.forEach(function(l){lb.appendChild(el('div',null,'cycle '+(l.cycle||'?')+' · reflection'))})}else lb.appendChild(el('div','muted','No lessons yet'));
 g.appendChild(card('Self-improvement lessons',lb));
}
tick();setInterval(tick,4000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/state"):
            body = json.dumps(_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    print(f"AgentGRIT HUD -> http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
