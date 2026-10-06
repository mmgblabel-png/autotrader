"""Standalone Coinbase-only control dashboard.

This page intentionally contains no Bitvavo portfolio, order, PnL or control data.
"""

from __future__ import annotations


COINBASE_DASHBOARD_HTML = r'''<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coinbase Agent | Dedicated Control Room</title>
<style>
:root{--bg:#050b18;--panel:#0b1528;--panel2:#101d35;--line:#203252;--text:#f4f7ff;--muted:#8fa4c5;--blue:#3773f5;--blue2:#6ba4ff;--green:#31d19a;--amber:#f2b84b;--red:#ff6577}
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;background:radial-gradient(circle at 80% 0,#153b87 0,#081126 34%,#050b18 70%)}
.hidden{display:none!important}.wrap{max-width:1440px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:22px}.brand{display:flex;align-items:center;gap:15px}.logo{width:52px;height:52px;border-radius:50%;background:#fff;color:#1652f0;display:grid;place-items:center;font-size:26px;font-weight:950;box-shadow:0 0 0 6px #1652f022}.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--blue2);font-weight:850}.title{font-size:30px;font-weight:900;margin-top:3px}.sub{color:var(--muted);font-size:12px}.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button,.btn{border:0;border-radius:10px;padding:11px 15px;font-weight:850;cursor:pointer;background:var(--blue);color:#fff}button.secondary,.btn.secondary{background:#0d1930;color:var(--text);border:1px solid var(--line)}button.danger{background:#3a1821;color:#ffdbe1;border:1px solid #7a3241}button:disabled{opacity:.45;cursor:not-allowed}.pill,.badge{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:999px;padding:7px 11px;color:var(--muted);font-size:11px}.badge.ok{color:var(--green);border-color:#23604f}.badge.warn{color:var(--amber);border-color:#6c5122}.badge.bad{color:var(--red);border-color:#743342}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 13px var(--green)}.dot.off{background:var(--red);box-shadow:0 0 13px var(--red)}
.login{max-width:430px;margin:10vh auto;padding:28px;background:#0b1528ee;border:1px solid var(--line);border-radius:22px;box-shadow:0 30px 90px #0008}.login h1{margin:5px 0 6px}.field{display:grid;gap:7px;margin:14px 0}.field label{font-size:11px;color:var(--muted)}input{width:100%;border:1px solid var(--line);background:#071126;color:var(--text);border-radius:10px;padding:12px;outline:none}input:focus{border-color:var(--blue)}.err{min-height:20px;color:var(--red);font-size:12px;margin-top:10px}
.hero{display:grid;grid-template-columns:1.4fr repeat(3,1fr);gap:14px}.card{background:linear-gradient(145deg,#101d35f5,#091426f5);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 14px 40px #0003}.hero-main{min-height:136px;background:linear-gradient(135deg,#153873dd,#0b1a34 65%)}.label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.value{font-size:28px;font-weight:900;margin-top:8px}.big{font-size:37px}.green{color:var(--green)}.blue{color:var(--blue2)}.amber{color:var(--amber)}.red{color:var(--red)}
.section{margin-top:18px}.section-title{display:flex;align-items:center;gap:12px;margin:24px 0 10px}.section-title h2{font-size:13px;margin:0;text-transform:uppercase;letter-spacing:.12em;color:#b7c7e4}.section-title .line{height:1px;background:var(--line);flex:1}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.two{display:grid;grid-template-columns:1.15fr .85fr;gap:14px}.metric{display:flex;justify-content:space-between;gap:15px;padding:11px 0;border-bottom:1px solid #182943;color:var(--muted);font-size:12px}.metric b{color:var(--text);text-align:right}.bar{height:10px;border-radius:99px;background:#071126;overflow:hidden;margin:10px 0}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--green));border-radius:inherit}.notice{padding:12px 14px;border-radius:10px;background:#131d31;border-left:3px solid var(--blue);font-size:12px;color:#c9d6ee}.notice.warn{border-left-color:var(--amber);background:#2b2414}.table-wrap{overflow:auto;border:1px solid #1b2d49;border-radius:12px;max-height:400px}.table{width:100%;border-collapse:collapse;font-size:12px;min-width:680px}.table th{text-align:left;position:sticky;top:0;background:#101d35;color:var(--muted);padding:10px;border-bottom:1px solid var(--line)}.table td{padding:11px 10px;border-bottom:1px solid #172740}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}.foot{display:flex;justify-content:space-between;gap:10px;margin-top:20px;color:var(--muted);font-size:10px}
.gates{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.gate{border:1px solid var(--line);background:#081326;border-radius:999px;padding:6px 9px;font-size:10px;color:var(--muted)}.gate.pass{color:var(--green);border-color:#245b4c}.gate.fail{color:var(--amber);border-color:#695323}
@media(max-width:1000px){.hero,.grid4{grid-template-columns:repeat(2,1fr)}.two,.grid3{grid-template-columns:1fr}}@media(max-width:600px){.wrap{padding:15px}.top{align-items:flex-start;flex-direction:column}.hero,.grid4{grid-template-columns:1fr}}
</style>
</head>
<body>
<div id="login" class="login">
  <div class="eyebrow">Coinbase dedicated control room</div>
  <h1>Coinbase Agent</h1>
  <p class="sub">Alleen Coinbase Agent-data, Coinbase execution en Coinbase-controls.</p>
  <div class="field"><label>Gebruikersnaam</label><input id="username" value="admin" autocomplete="username"></div>
  <div class="field"><label>Wachtwoord</label><input id="password" type="password" autocomplete="current-password"></div>
  <div class="field"><label>Of API-key</label><input id="apikey" type="password" placeholder="X-API-Key (optioneel)" autocomplete="off"></div>
  <button onclick="login()">Coinbase Dashboard openen</button><div id="loginerr" class="err"></div>
</div>

<div id="app" class="hidden"><div class="wrap">
<header class="top">
  <div class="brand"><div class="logo">C</div><div><div class="eyebrow">Dedicated Coinbase Agent</div><div class="title">Coinbase Control Room</div><div class="sub">Isolated portfolio · BTC-EUR SPOT · autonome evidence-gated execution</div></div></div>
  <div class="actions"><span class="pill"><span id="statusdot" class="dot off"></span><b id="topstatus">CONTROLEREN</b></span><button class="secondary" onclick="refresh()">Vernieuwen</button><button id="livebtn" onclick="activateLive()" disabled>Coinbase Live</button><button id="stopbtn" class="danger hidden" onclick="deactivateLive()">Stop Live</button><button class="secondary" onclick="logout()">Uitloggen</button></div>
</header>

<div id="notice" class="notice">Coinbase-data laden…</div>

<section class="section hero">
  <div class="card hero-main"><div class="label">Agent portfolio</div><div id="agentcash" class="value big">—</div><div id="portfolioscope" class="sub">Dedicated isolated Coinbase portfolio</div><div class="gates"><span class="gate">20% max / trade</span><span class="gate">20% cash reserve</span><span class="gate">3% daily loss</span><span class="gate">10% drawdown</span></div></div>
  <div class="card"><div class="label">Live status</div><div id="armed" class="value">—</div><div id="armedsub" class="sub">—</div></div>
  <div class="card"><div class="label">Evidence</div><div id="evidence" class="value blue">—</div><div id="evidencesub" class="sub">settled shadow trades</div></div>
  <div class="card"><div class="label">Execution scope</div><div id="scope" class="value">BTC-EUR</div><div class="sub">SPOT only · geen leverage/margin/futures</div></div>
</section>

<div class="section-title"><h2>Execution & risk</h2><div class="line"></div><span id="readybadge" class="badge">READINESS</span></div>
<section class="grid4">
  <div class="card"><div class="label">Max entry nu</div><div id="maxtrade" class="value">—</div><div class="sub">20% van geïsoleerde NAV</div></div>
  <div class="card"><div class="label">Cash reserve</div><div id="reserve" class="value">—</div><div class="sub">blijft buiten nieuwe entries</div></div>
  <div class="card"><div class="label">Live orders sent</div><div id="orderssent" class="value">—</div><div id="legacyorders" class="sub">—</div></div>
  <div class="card"><div class="label">Runtime error</div><div id="runtimeerror" class="value">—</div><div class="sub">Coinbase autonomous executor</div></div>
</section>

<section class="section two">
  <div class="card">
    <div class="label">Readiness gates</div>
    <div id="gatechips" class="gates"></div>
    <div class="metric"><span>Ready to arm</span><b id="readytoarm">—</b></div>
    <div class="metric"><span>Execution ready now</span><b id="execnow">—</b></div>
    <div class="metric"><span>Trade permission preview</span><b id="preview">—</b></div>
    <div class="metric"><span>Persistent operator intent</span><b id="intent">—</b></div>
    <div class="metric"><span>Portfolio isolated</span><b id="isolated">—</b></div>
  </div>
  <div class="card">
    <div class="label">Agent balances</div>
    <div id="balances"></div>
    <div class="notice" style="margin-top:12px">Deze kaart leest uitsluitend het geconfigureerde Coinbase Agent-portfolio. Andere Coinbase-portfolios worden niet in dit dashboard getoond.</div>
  </div>
</section>

<div class="section-title"><h2>Shadow evidence engine</h2><div class="line"></div><span id="shadowbadge" class="badge">EVIDENCE</span></div>
<section class="section two">
  <div class="card">
    <div class="grid3">
      <div><div class="label">Winrate</div><div id="winrate" class="value">—</div></div>
      <div><div class="label">Net PnL</div><div id="shadowpnl" class="value">—</div></div>
      <div><div class="label">Profit factor</div><div id="pf" class="value">—</div></div>
    </div>
    <div class="bar"><i id="evidencebar" style="width:0%"></i></div>
    <div class="metric"><span>Evidence progress</span><b id="evidenceprogress">—</b></div>
    <div class="metric"><span>Max drawdown</span><b id="shadowdd">—</b></div>
    <div class="metric"><span>Laatste BTC-EUR prijs</span><b id="lastprice">—</b></div>
    <div class="metric"><span>Laatste beslisreden</span><b id="decisionreason">—</b></div>
    <div class="metric"><span>Horizons</span><b>5m · 15m · 30m · 60m</b></div>
  </div>
  <div class="card">
    <div class="label">Promotion blockers</div>
    <div id="blockers" class="gates"></div>
    <div class="metric"><span>Minimum settled</span><b id="minsettled">—</b></div>
    <div class="metric"><span>Minimum winrate</span><b id="minwinrate">—</b></div>
    <div class="metric"><span>Minimum net PnL</span><b id="minpnl">—</b></div>
    <div class="metric"><span>Minimum profit factor</span><b id="minpf">—</b></div>
    <div class="metric"><span>Max shadow drawdown</span><b id="maxshadowdd">—</b></div>
  </div>
</section>

<div class="section-title"><h2>Coinbase market discovery</h2><div class="line"></div><span class="badge">READ ONLY</span></div>
<section class="grid4">
  <div class="card"><div class="label">Coinbase markets</div><div id="markets" class="value">—</div></div>
  <div class="card"><div class="label">Tradable</div><div id="tradable" class="value">—</div></div>
  <div class="card"><div class="label">Crypto → crypto</div><div id="cryptocrypto" class="value">—</div></div>
  <div class="card"><div class="label">EUR quote</div><div id="eurquote" class="value">—</div></div>
</section>

<div class="section-title"><h2>Coinbase execution audit</h2><div class="line"></div><span class="badge">PERSISTENT</span></div>
<section class="card">
  <div class="table-wrap"><table class="table"><thead><tr><th>Tijd</th><th>Actie</th><th>Product</th><th>Side</th><th>Notional / size</th><th>Status / reason</th></tr></thead><tbody id="auditrows"><tr><td colspan="6" class="sub">Audit laden…</td></tr></tbody></table></div>
</section>

<div class="foot"><span>Dedicated Coinbase Agent dashboard</span><span id="updated">—</span></div>
</div></div>

<script>
let token="", apiKey="";
const euro=v=>Number(v||0).toLocaleString("nl-NL",{style:"currency",currency:"EUR",minimumFractionDigits:2,maximumFractionDigits:4});
const pct=v=>Number(v||0).toLocaleString("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2})+"%";
const num=v=>Number(v||0).toLocaleString("nl-NL",{maximumFractionDigits:4});
function headers(extra={}){const h={"Content-Type":"application/json",...extra};if(token)h.Authorization="Bearer "+token;if(apiKey)h["X-API-Key"]=apiKey;return h}
async function api(path,opt={}){const r=await fetch(path,{...opt,headers:headers(opt.headers||{})});let data={};try{data=await r.json()}catch{}if(!r.ok)throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data));return data}
async function login(){
  document.getElementById("loginerr").textContent="";
  apiKey=document.getElementById("apikey").value.trim();
  try{
    if(!apiKey){const x=await api("/api/auth/login",{method:"POST",body:JSON.stringify({username:document.getElementById("username").value,password:document.getElementById("password").value})});token=x.access_token}
    document.getElementById("login").classList.add("hidden");document.getElementById("app").classList.remove("hidden");await refresh();setInterval(refresh,10000)
  }catch(e){document.getElementById("loginerr").textContent=e.message}
}
function logout(){token="";apiKey="";location.reload()}
function yes(v){return v?'<span class="green">JA</span>':'<span class="red">NEE</span>'}
function setText(id,v){document.getElementById(id).textContent=v}
function auditRows(rows){
  if(!Array.isArray(rows)||!rows.length)return '<tr><td colspan="6" class="sub">Nog geen nieuwe geaudite Coinbase execution-events.</td></tr>';
  return rows.slice().reverse().map(r=>{
    const t=r.at?new Date(Number(r.at)*1000).toLocaleString("nl-NL"):"—";
    const side=r.side||"—"; const amt=r.notional_eur??r.quote_size??r.base_size??r.managed_cash_eur??"—";
    return '<tr><td class="mono">'+t+'</td><td>'+(r.action||r.event||"—")+'</td><td>'+(r.product_id||"BTC-EUR")+'</td><td>'+side+'</td><td class="mono">'+amt+'</td><td>'+(r.status||r.reason||r.error||"—")+'</td></tr>'
  }).join("")
}
function gateChips(failed){
  const known=["enabled","execution_mode_live","live_approved","adapter_installed","coinbase_live_enabled","emergency_stop_off","confirmation","runtime_armed","credentials_compatible","authenticated","isolated_portfolio_configured","shadow_promotion_ready"];
  const f=new Set(failed||[]);return known.map(g=>'<span class="gate '+(f.has(g)?'fail':'pass')+'">'+(f.has(g)?'WAIT ':'OK ')+g+'</span>').join("")
}
async function refresh(){
  try{
    const d=await api("/api/coinbase/dashboard/snapshot");
    const a=d.autonomous||{}, r=d.readiness||{}, s=d.shadow||{}, b=d.balances||{}, u=d.universe||{};
    const rd=a.readiness||{}; const assets=b.assets||[]; const eur=assets.find(x=>x.currency==="EUR");
    setText("agentcash",euro(eur?eur.total:rd.portfolio_nav_eur||0));
    setText("portfolioscope",b.portfolio_scoped?"Dedicated isolated Coinbase portfolio":"PORTFOLIO SCOPE NIET BEVESTIGD");
    const armed=!!a.coinbase_armed; setText("armed",armed?"ARMED":"OFF"); document.getElementById("armed").className="value "+(armed?"green":"red");
    setText("armedsub",armed?"Agent mag handelen zodra evidence + risk gates groen zijn":"Live execution is gedeactiveerd");
    document.getElementById("statusdot").className="dot "+(armed?"":"off");setText("topstatus",armed?"COINBASE LIVE":"COINBASE OFF");
    document.getElementById("livebtn").disabled=armed||!r.ready_to_arm;document.getElementById("stopbtn").classList.toggle("hidden",!armed);
    const settled=Number(s.settled_trades||0), min=Number((s.promotion_policy||{}).min_settled_trades||30);
    setText("evidence",settled+" / "+min);setText("evidencesub","settled shadow trades · "+(s.promotion_ready?"PROMOTED":"evidence verzamelen"));
    setText("maxtrade",euro(rd.max_single_trade_eur||0));setText("reserve",euro(rd.required_cash_reserve_eur||0));
    setText("orderssent",a.live_orders_sent??0);setText("legacyorders",(a.unattributed_legacy_live_orders||0)+" legacy unattributed");
    setText("runtimeerror",a.runtime_error||"GEEN");document.getElementById("runtimeerror").className="value "+(a.runtime_error?"red":"green");
    document.getElementById("gatechips").innerHTML=gateChips(r.execution_failed_gates||r.failed_gates||[]);
    setText("readytoarm",r.ready_to_arm?"JA":"NEE");setText("execnow",r.execution_ready_now?"JA":"NEE");
    setText("preview",(r.trade_permission_preview||{}).passed?"OK":"BLOKKADE");
    setText("intent",((r.arm_persistence||{}).persisted_armed)?"ARMED INTENT":"OFF");
    setText("isolated",b.portfolio_scoped?"JA":"NEE");
    document.getElementById("balances").innerHTML=assets.length?assets.map(x=>'<div class="metric"><span>'+x.currency+'</span><b>'+x.available+' beschikbaar · '+x.hold+' hold</b></div>').join(""):'<div class="sub">Geen assets.</div>';
    setText("winrate",pct(s.winrate_pct));setText("shadowpnl",euro(s.realized_pnl_eur));setText("pf",s.profit_factor==null?"∞":num(s.profit_factor));
    setText("shadowdd",pct(s.max_drawdown_pct));setText("lastprice",s.last_mid_price?euro(s.last_mid_price):"—");
    const decisions=((s.last_signal||{}).decisions||[]);setText("decisionreason",decisions.length?(decisions[decisions.length-1].reason||decisions[decisions.length-1].decision||"—"):"—");
    const progress=Math.min(100,min?settled/min*100:0);document.getElementById("evidencebar").style.width=progress+"%";setText("evidenceprogress",settled+" / "+min+" ("+progress.toFixed(0)+"%)");
    const blockers=s.promotion_blockers||[];document.getElementById("blockers").innerHTML=(blockers.length?blockers:["geen blockers"]).map(x=>'<span class="gate '+(blockers.length?"fail":"pass")+'">'+x+'</span>').join("");
    const pol=s.promotion_policy||{};setText("minsettled",pol.min_settled_trades??"—");setText("minwinrate",pct(pol.min_winrate_pct));setText("minpnl",euro(pol.min_net_pnl_eur));setText("minpf",num(pol.min_profit_factor));setText("maxshadowdd",pct(pol.max_drawdown_pct));
    setText("markets",u.all??0);setText("tradable",u.tradable??0);setText("cryptocrypto",u.crypto_crypto??0);setText("eurquote",u.eur_quote??0);
    document.getElementById("auditrows").innerHTML=auditRows(a.order_audit||[]);
    const ready=!!r.execution_ready_now, promote=!!s.promotion_ready;
    document.getElementById("readybadge").className="badge "+(ready?"ok":"warn");setText("readybadge",ready?"EXECUTION READY":"GATED");
    document.getElementById("shadowbadge").className="badge "+(promote?"ok":"warn");setText("shadowbadge",promote?"PROMOTION READY":"BUILDING EVIDENCE");
    const msg=armed?(ready?"Coinbase Agent is armed en execution-ready.":"Coinbase Agent is armed; nieuwe entries wachten nog op: "+(r.execution_failed_gates||[]).join(", ")):"Coinbase Live staat uit. De shadow engine blijft evidence verzamelen.";
    document.getElementById("notice").textContent=msg;document.getElementById("notice").className="notice "+((armed&&!ready)||!armed?"warn":"");
    setText("updated","Bijgewerkt "+new Date().toLocaleTimeString("nl-NL"));
  }catch(e){document.getElementById("notice").textContent="Dashboard update mislukt: "+e.message;document.getElementById("notice").className="notice warn"}
}
async function activateLive(){
  try{
    const ctl=prompt("Vul je AUTOTRADER_CONTROL_TOKEN in. Dit wordt niet opgeslagen.");
    if(!ctl)return;
    const phrase=prompt("Bevestig door exact I_UNDERSTAND_COINBASE_LIVE_ORDERS in te vullen.");
    if(phrase!=="I_UNDERSTAND_COINBASE_LIVE_ORDERS")return;
    await api("/api/coinbase/live/activate",{method:"POST",headers:{"X-Autotrader-Token":ctl},body:JSON.stringify({confirmation:phrase})});
    await refresh();
  }catch(e){alert("Coinbase Live niet geactiveerd: "+e.message)}
}
async function deactivateLive(){
  try{
    const ctl=prompt("Vul je AUTOTRADER_CONTROL_TOKEN in. Dit wordt niet opgeslagen.");
    if(!ctl)return;
    await api("/api/coinbase/live/deactivate",{method:"POST",headers:{"X-Autotrader-Token":ctl},body:"{}"});
    await refresh();
  }catch(e){alert("Coinbase Live niet gestopt: "+e.message)}
}
</script>
</body></html>'''


def coinbase_dashboard_html() -> str:
    return COINBASE_DASHBOARD_HTML
