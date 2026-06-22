"""Self-contained, offline HTML dashboard generator.

Mirrors the Grafana dashboard but renders from captured time-series so it runs
with zero infrastructure. Charts are drawn with a tiny embedded vanilla-JS canvas
renderer (no CDN, works offline). Use it to *see* the lifecycle: provisioning
ramp, steady state, an injected failure, self-heal recovery, and decommission.
"""
from __future__ import annotations

import json
from collections import OrderedDict

STATE_COLORS = {
    "REQUESTED": "#9aa5b1", "PROVISIONING": "#f0b429", "BOOTSTRAPPING": "#f7c948",
    "REGISTERING": "#7bd389", "HEALTHY": "#27ab83", "UPDATING": "#2bb0ed",
    "DRAINING": "#f9703e", "DECOMMISSIONING": "#e12d39", "FAILED": "#cf1124",
    "TERMINATED": "#52606d",
}
PROVIDER_COLORS = {
    "aws": "#ff9900", "gcp": "#4285f4", "azure": "#0078d4", "baremetal": "#7b61ff",
}


class DashboardData:
    """Collects per-tick time-series from a Telemetry + Store during a run."""

    def __init__(self):
        self.ticks: list[int] = []
        self.total_healthy: list[float] = []
        self.total_desired: list[float] = []
        self.availability: list[float] = []
        self.healthy_by_provider: dict[str, list[float]] = OrderedDict()
        self.nodes_by_state: dict[str, list[float]] = OrderedDict()
        self.failures_cum: list[float] = []
        self.selfheal_cum: list[float] = []
        self.created_cum: list[float] = []
        self.events: list[dict] = []  # annotations (tick, label)

    def capture(self, tick: int, telemetry, store) -> None:
        snap = telemetry.registry.snapshot()
        self.ticks.append(tick)

        def sum_metric(name: str) -> float:
            return sum(v for (n, _), v in snap.items() if n == name)

        healthy = sum_metric("clusterinfra_pool_healthy_nodes")
        desired = sum_metric("clusterinfra_pool_desired_nodes")
        self.total_healthy.append(healthy)
        self.total_desired.append(desired)
        self.availability.append(round(healthy / desired, 4) if desired else 1.0)

        # healthy by provider
        prov: dict[str, float] = {}
        for (n, key), v in snap.items():
            if n == "clusterinfra_pool_healthy_nodes":
                labels = dict(key)
                prov[labels["provider"]] = prov.get(labels["provider"], 0) + v
        for p in set(list(prov) + list(self.healthy_by_provider)):
            self.healthy_by_provider.setdefault(p, [0.0] * (len(self.ticks) - 1))
            self.healthy_by_provider[p].append(prov.get(p, 0.0))

        # nodes by state
        st: dict[str, float] = {}
        for (n, key), v in snap.items():
            if n == "clusterinfra_nodes":
                st[dict(key)["state"]] = st.get(dict(key)["state"], 0) + v
        for s in set(list(st) + list(self.nodes_by_state)):
            self.nodes_by_state.setdefault(s, [0.0] * (len(self.ticks) - 1))
            self.nodes_by_state[s].append(st.get(s, 0.0))

        self.failures_cum.append(sum_metric("clusterinfra_nodes_failed_total"))
        self.selfheal_cum.append(sum_metric("clusterinfra_self_heal_total"))
        self.created_cum.append(sum_metric("clusterinfra_nodes_created_total"))

    def event(self, label: str) -> None:
        self.events.append({"tick": self.ticks[-1] if self.ticks else 0,
                            "label": label})


def render_html(data: DashboardData, prometheus_text: str,
                title: str = "Cluster Infra — Fleet Lifecycle & Health") -> str:
    payload = {
        "ticks": data.ticks,
        "total_healthy": data.total_healthy,
        "total_desired": data.total_desired,
        "availability": data.availability,
        "healthy_by_provider": data.healthy_by_provider,
        "nodes_by_state": data.nodes_by_state,
        "failures_cum": data.failures_cum,
        "selfheal_cum": data.selfheal_cum,
        "created_cum": data.created_cum,
        "events": data.events,
        "state_colors": STATE_COLORS,
        "provider_colors": PROVIDER_COLORS,
    }
    data_json = json.dumps(payload)
    prom = (prometheus_text or "").replace("<", "&lt;")
    return _TEMPLATE.replace("__TITLE__", title) \
                    .replace("__DATA__", data_json) \
                    .replace("__PROM__", prom)


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
 :root{--bg:#0b1020;--panel:#141b2e;--ink:#e6edf7;--muted:#8b97ad;--grid:#26314d;}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
   font:14px/1.4 -apple-system,Segoe UI,Roboto,Helvetica,Arial}
 header{padding:16px 24px;border-bottom:1px solid var(--grid);display:flex;
   align-items:baseline;gap:16px} h1{font-size:18px;margin:0}
 .sub{color:var(--muted)} .grid{display:grid;grid-template-columns:repeat(12,1fr);
   gap:14px;padding:18px 24px}
 .panel{background:var(--panel);border:1px solid var(--grid);border-radius:10px;
   padding:12px 14px;min-height:90px}
 .panel h3{margin:0 0 8px;font-size:12px;color:var(--muted);font-weight:600;
   text-transform:uppercase;letter-spacing:.04em}
 .stat .v{font-size:30px;font-weight:700} .stat .u{color:var(--muted);font-size:12px}
 .w3{grid-column:span 3}.w4{grid-column:span 4}.w6{grid-column:span 6}
 .w8{grid-column:span 8}.w12{grid-column:span 12}
 canvas{width:100%;height:200px;display:block}
 .legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;font-size:12px;color:var(--muted)}
 .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
 pre{background:#0a0f1d;border:1px solid var(--grid);border-radius:8px;padding:12px;
   max-height:320px;overflow:auto;color:#a9b7d0;font-size:12px}
 .good{color:#41d18b}.warn{color:#f0b429}.bad{color:#ff6b6b}
</style></head><body>
<header><h1>__TITLE__</h1><span class="sub" id="meta"></span></header>
<div class="grid">
  <div class="panel stat w3"><h3>Healthy nodes</h3><div class="v" id="s_healthy">–</div><span class="u" id="s_healthy_u"></span></div>
  <div class="panel stat w3"><h3>Desired nodes</h3><div class="v" id="s_desired">–</div></div>
  <div class="panel stat w3"><h3>Fleet availability</h3><div class="v" id="s_avail">–</div><span class="u">healthy / desired</span></div>
  <div class="panel stat w3"><h3>Self-heals (cum)</h3><div class="v" id="s_heal">–</div></div>

  <div class="panel w6"><h3>Nodes by lifecycle state</h3><canvas id="c_state"></canvas><div class="legend" id="l_state"></div></div>
  <div class="panel w6"><h3>Healthy nodes by provider</h3><canvas id="c_prov"></canvas><div class="legend" id="l_prov"></div></div>

  <div class="panel w6"><h3>Fleet availability ratio</h3><canvas id="c_avail"></canvas></div>
  <div class="panel w6"><h3>Cumulative: created / failed / self-heal</h3><canvas id="c_counters"></canvas><div class="legend" id="l_counters"></div></div>

  <div class="panel w12"><h3>Prometheus exposition (live scrape sample)</h3><pre id="prom">__PROM__</pre></div>
</div>
<script>
const D = __DATA__;
const fmt = n => Math.round(n).toLocaleString();
document.getElementById('meta').textContent =
  `${D.ticks.length} ticks  ·  events: ` + (D.events.map(e=>`${e.label}@t${e.tick}`).join('  ·  ')||'none');

const last = a => a.length? a[a.length-1] : 0;
document.getElementById('s_healthy').textContent = fmt(last(D.total_healthy));
document.getElementById('s_healthy_u').textContent = 'of ' + fmt(last(D.total_desired));
document.getElementById('s_desired').textContent = fmt(last(D.total_desired));
const av = last(D.availability);
const avEl = document.getElementById('s_avail');
avEl.textContent = (av*100).toFixed(1) + '%';
avEl.className = 'v ' + (av>=0.99?'good':av>=0.9?'warn':'bad');
document.getElementById('s_heal').textContent = fmt(last(D.selfheal_cum));

function setup(cv){const r=window.devicePixelRatio||1;const w=cv.clientWidth,h=cv.clientHeight;
  cv.width=w*r;cv.height=h*r;const x=cv.getContext('2d');x.scale(r,r);return [x,w,h];}
function axes(x,w,h,maxY){x.strokeStyle='#26314d';x.lineWidth=1;x.beginPath();
  for(let i=0;i<=4;i++){const y=10+(h-30)*i/4;x.moveTo(40,y);x.lineTo(w-8,y);}
  x.stroke();x.fillStyle='#8b97ad';x.font='10px sans-serif';
  for(let i=0;i<=4;i++){const y=10+(h-30)*i/4;const val=maxY*(1-i/4);
    x.fillText(Math.round(val),4,y+3);}}
function xpos(i,n,w){return 40+(w-48)*(n<=1?0:i/(n-1));}
function line(cv,series,colors,maxY){const [x,w,h]=setup(cv);maxY=maxY||1;axes(x,w,h,maxY);
  const ph=h-30;Object.keys(series).forEach(k=>{const ys=series[k];x.strokeStyle=colors[k]||'#7bd389';
    x.lineWidth=2;x.beginPath();ys.forEach((v,i)=>{const px=xpos(i,ys.length,w);
      const py=10+ph*(1-Math.min(v/maxY,1));i?x.lineTo(px,py):x.moveTo(px,py);});x.stroke();});}
function stack(cv,series,colors){const [x,w,h]=setup(cv);const keys=Object.keys(series);
  const n=(series[keys[0]]||[]).length;let maxY=0;
  for(let i=0;i<n;i++){let s=0;keys.forEach(k=>s+=series[k][i]||0);maxY=Math.max(maxY,s);}
  maxY=maxY||1;axes(x,w,h,maxY);const ph=h-30;
  for(let i=0;i<n;i++){let acc=0;const px=xpos(i,n,w);const bw=Math.max(2,(w-48)/n*0.9);
    keys.forEach(k=>{const v=series[k][i]||0;const bh=ph*(v/maxY);
      x.fillStyle=colors[k]||'#7bd389';x.fillRect(px-bw/2,10+ph-acc-bh,bw,bh);acc+=bh;});}}
function legend(el,keys,colors){el.innerHTML=keys.map(k=>
  `<span><i style="background:${colors[k]||'#7bd389'}"></i>${k}</span>`).join('');}

stack(document.getElementById('c_state'),D.nodes_by_state,D.state_colors);
legend(document.getElementById('l_state'),Object.keys(D.nodes_by_state),D.state_colors);
stack(document.getElementById('c_prov'),D.healthy_by_provider,D.provider_colors);
legend(document.getElementById('l_prov'),Object.keys(D.healthy_by_provider),D.provider_colors);
line(document.getElementById('c_avail'),{availability:D.availability},{availability:'#27ab83'},1);
const cnt={created:D.created_cum,failed:D.failures_cum,'self-heal':D.selfheal_cum};
const cmax=Math.max(1,...D.created_cum,...D.failures_cum,...D.selfheal_cum);
line(document.getElementById('c_counters'),cnt,{created:'#2bb0ed',failed:'#cf1124','self-heal':'#f0b429'},cmax);
legend(document.getElementById('l_counters'),Object.keys(cnt),{created:'#2bb0ed',failed:'#cf1124','self-heal':'#f0b429'});
</script></body></html>"""
