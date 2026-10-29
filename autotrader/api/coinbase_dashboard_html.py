"""Professional one-page Coinbase RiskTrader dashboard.

Coinbase-only. The page intentionally excludes Bitvavo and other portfolios.
"""

from __future__ import annotations


COINBASE_DASHBOARD_HTML = r'''<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coinbase RiskTrader | Control Room</title>
<style>
:root{
  --bg:#050914;--panel:#0b1424;--panel2:#0f1b30;--panel3:#111f37;--line:#1f304b;
  --text:#f5f7fb;--muted:#8ea0bc;--blue:#3773f5;--blue2:#78a6ff;--green:#39d39f;
  --red:#ff667a;--amber:#f0b74b;--shadow:0 18px 55px rgba(0,0,0,.28)
}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;min-height:100vh;background:
radial-gradient(circle at 85% -10%,#1b438e 0,transparent 29%),
linear-gradient(180deg,#07101f 0,#050914 38%,#040812 100%);
color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}
.hidden{display:none!important}.wrap{max-width:1500px;margin:auto;padding:24px}
header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:18px}
.brand{display:flex;align-items:center;gap:14px}.coin{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;background:#fff;color:#1652f0;font-size:25px;font-weight:950;box-shadow:0 0 0 5px rgba(22,82,240,.14)}
.eyebrow,.kicker{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--blue2);font-weight:850}
h1{font-size:27px;margin:3px 0 2px}.subtitle{color:var(--muted);font-size:12px}
.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
button{border:0;border-radius:10px;padding:10px 14px;font-weight:800;color:#fff;background:var(--blue);cursor:pointer}
button.secondary{background:#0b1629;border:1px solid var(--line)}button.danger{background:#35151e;border:1px solid #74303f}
button:disabled{opacity:.45;cursor:not-allowed}
.statuspill,.tag{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border-radius:999px;border:1px solid var(--line);font-size:10px;color:var(--muted);font-weight:750}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 12px var(--green)}.dot.off{background:var(--red);box-shadow:0 0 12px var(--red)}
.notice{border:1px solid #264578;background:#0b1a32;border-left:3px solid var(--blue);border-radius:12px;padding:12px 14px;color:#cbd8ee;font-size:12px;margin-bottom:14px}
.notice.warn{border-left-color:var(--amber);background:#251e10;border-color:#54431f}.notice.bad{border-left-color:var(--red);background:#27121a;border-color:#5b2734}
.grid5{display:grid;grid-template-columns:1.2fr repeat(4,1fr);gap:12px}.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.two{display:grid;grid-template-columns:1.25fr .75fr;gap:12px}.two-even{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:linear-gradient(145deg,rgba(16,29,51,.97),rgba(8,18,34,.97));border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:var(--shadow)}
.hero{background:linear-gradient(135deg,#153971cc,#0b1a34 67%)}
.label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:800}.value{font-size:27px;font-weight:900;margin-top:7px;line-height:1.05}.value.big{font-size:34px}.sub{font-size:11px;color:var(--muted);margin-top:5px;line-height:1.45}
.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.blue{color:var(--blue2)}
.sectionhead{display:flex;align-items:center;gap:12px;margin:20px 0 9px}.sectionhead h2{font-size:12px;margin:0;text-transform:uppercase;letter-spacing:.13em;color:#bdc9dd}.sectionhead i{height:1px;background:var(--line);flex:1}
.livebox{display:grid;grid-template-columns:1.2fr .8fr;gap:14px;align-items:stretch}.activity{min-height:215px}
.activitytop{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.activitytitle{font-size:25px;font-weight:900;margin:8px 0 3px}.activitymeta{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}
.metric{display:flex;justify-content:space-between;gap:15px;padding:10px 0;border-bottom:1px solid #182942;color:var(--muted);font-size:11px}.metric:last-child{border-bottom:0}.metric b{color:var(--text);text-align:right}
.pnlbreakdown{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.mini{background:#091426;border:1px solid #1c2d48;border-radius:11px;padding:11px}.mini b{display:block;font-size:16px;margin-top:4px}
.chartbox{height:160px;margin-top:10px;background:#071121;border:1px solid #172944;border-radius:12px;overflow:hidden;position:relative}.chartbox svg{width:100%;height:100%}.chart-empty{display:grid;place-items:center;height:100%;color:var(--muted);font-size:11px}
.tablewrap{overflow:auto;border:1px solid #1b2e49;border-radius:12px}.table{width:100%;border-collapse:collapse;min-width:950px;font-size:11px}.table th{position:sticky;top:0;text-align:left;background:#101d35;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.04em;padding:10px;border-bottom:1px solid var(--line)}.table td{padding:11px 10px;border-bottom:1px solid #172740;vertical-align:middle}.table tr:last-child td{border-bottom:0}
.result{font-weight:900}.reason{display:inline-flex;padding:4px 7px;border-radius:999px;background:#0a172a;border:1px solid #213753;color:#b9c8df}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.progress{height:8px;background:#071020;border-radius:999px;overflow:hidden;margin-top:9px}.progress i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--green));border-radius:inherit}
.gates{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.gate{font-size:9px;padding:5px 7px;border-radius:999px;border:1px solid #245342;color:var(--green);background:#071a17}.gate.fail{border-color:#6f4e22;color:var(--amber);background:#1f1809}
.insight{padding:12px;border-radius:11px;background:#0a1527;border:1px solid #1c304c;margin-top:10px;font-size:11px;line-height:1.55;color:#c7d3e7}.insight strong{color:#fff}
.login{max-width:420px;margin:12vh auto;padding:26px;background:#0b1528f7;border:1px solid var(--line);border-radius:20px;box-shadow:0 35px 90px #0008}.login h2{margin:5px 0}.field{display:grid;gap:6px;margin:13px 0}.field label{font-size:10px;color:var(--muted)}input{width:100%;padding:11px;border-radius:9px;border:1px solid var(--line);background:#071126;color:var(--text);outline:none}.err{min-height:18px;color:var(--red);font-size:11px;margin-top:8px}
.foot{display:flex;justify-content:space-between;gap:12px;margin:18px 0 5px;color:var(--muted);font-size:9px}
@media(max-width:1100px){.grid5{grid-template-columns:repeat(2,1fr)}.grid4{grid-template-columns:repeat(2,1fr)}.two,.two-even,.livebox{grid-template-columns:1fr}}
@media(max-width:650px){.wrap{padding:13px}header{align-items:flex-start;flex-direction:column}.grid5,.grid4{grid-template-columns:1fr}.pnlbreakdown{grid-template-columns:1fr}.value.big{font-size:30px}}
</style>
</head>
<body>
<div id="login" class="login">
  <div class="eyebrow">Coinbase RiskTrader</div><h2>Control Room</h2>
  <div class="subtitle">Eén dashboard voor geld, trades, redenen, risico en live execution.</div>
  <div class="field"><label>Gebruikersnaam</label><input id="username" value="admin"></div>
  <div class="field"><label>Wachtwoord</label><input id="password" type="password"></div>
  <div class="field"><label>Of lokale API-key</label><input id="apikey" type="password" placeholder="X-API-Key"></div>
  <button onclick="login()">Dashboard openen</button><div id="loginerr" class="err"></div>
</div>

<div id="app" class="hidden"><div class="wrap">
<header>
  <div class="brand"><div class="coin">C</div><div><div class="eyebrow">Dedicated Coinbase Agent</div><h1>RiskTrader Control Room</h1><div class="subtitle">Eén pagina · isolated portfolio · live spot execution · automatische refresh</div></div></div>
  <div class="actions">
    <span class="statuspill"><span id="statusdot" class="dot off"></span><span id="topstatus">CONTROLEREN</span></span>
    <button class="secondary" onclick="refresh()">Vernieuwen</button>
    <button id="livebtn" onclick="activateLive()" disabled>Live aan</button>
    <button id="stopbtn" class="danger hidden" onclick="deactivateLive()">Stop live</button>
    <button class="secondary" onclick="logout()">Uitloggen</button>
  </div>
</header>

<div id="notice" class="notice">Coinbase-data laden…</div>

<section class="grid5">
  <div class="card hero"><div class="label">Agent saldo totaal</div><div id="nav" class="value big">—</div><div id="navsub" class="sub">live isolated Coinbase saldo</div></div>
  <div class="card"><div class="label">PnL vandaag</div><div id="daypnl" class="value">—</div><div id="daypnlsub" class="sub">gerealiseerd na fees</div></div>
  <div class="card"><div class="label">USDC beschikbaar</div><div id="trades" class="value">—</div><div id="tradesub" class="sub">vrij voor nieuwe trades</div></div>
  <div class="card"><div class="label">EUR beschikbaar</div><div id="todaywinrate" class="value">—</div><div id="winsub" class="sub">vrij in Agent-portfolio</div></div>
  <div class="card"><div class="label">Bot nu</div><div id="exposure" class="value">—</div><div id="exposuresub" class="sub">actuele execution-state</div></div>
</section>

<div class="sectionhead"><h2>Wat gebeurt er nu?</h2><i></i><span id="readytag" class="tag">STATUS</span></div>
<section class="livebox">
  <div class="card activity">
    <div class="activitytop">
      <div><div class="label">Actieve state</div><div id="activitytitle" class="activitytitle">SCANNING</div><div id="activitysub" class="subtitle">Wachten op live data…</div></div>
      <span id="activitytag" class="tag">—</span>
    </div>
    <div class="activitymeta">
      <span class="tag" id="activityproduct">product —</span>
      <span class="tag" id="activityside">side —</span>
      <span class="tag" id="activitytype">type —</span>
      <span class="tag" id="activityrisk">risk —</span>
    </div>
    <div id="currentmetrics" style="margin-top:10px"></div>
  </div>
  <div class="card">
    <div class="label">Waarom winnen/verliezen we?</div>
    <div class="pnlbreakdown">
      <div class="mini"><span class="label">Prijsresultaat</span><b id="grosspnl">—</b></div>
      <div class="mini"><span class="label">Fees</span><b id="fees">—</b></div>
      <div class="mini"><span class="label">Netto</span><b id="netpnl">—</b></div>
    </div>
    <div id="lossinsight" class="insight">Trade-data wordt opgebouwd…</div>
  </div>
</section>

<div class="sectionhead"><h2>PnL vandaag</h2><i></i><span class="tag">CUMULATIEF</span></div>
<section class="card">
  <div id="pnlchart" class="chartbox"><div class="chart-empty">Nog geen gesloten trades vandaag.</div></div>
</section>

<div class="sectionhead"><h2>Trade journal</h2><i></i><span id="journalcount" class="tag">0 trades</span></div>
<section class="card">
  <div class="tablewrap"><table class="table">
    <thead><tr><th>Tijd</th><th>Markt</th><th>Risk</th><th>Entry</th><th>Exit</th><th>Fees</th><th>Netto PnL</th><th>Exitreden</th></tr></thead>
    <tbody id="journal"><tr><td colspan="8" class="subtitle">Trades laden…</td></tr></tbody>
  </table></div>
</section>

<div class="sectionhead"><h2>Market scanner</h2><i></i><span class="tag">LIVE INTELLIGENCE</span></div>
<section class="grid4">
  <div class="card"><div class="label">Markten gescand</div><div id="scanned" class="value">—</div><div id="eligible" class="sub">—</div></div>
  <div class="card"><div class="label">LONG signalen</div><div id="signals" class="value">—</div><div id="routes" class="sub">—</div></div>
  <div class="card"><div class="label">Beste kandidaat</div><div id="candidate" class="value">—</div><div id="candidateedge" class="sub">—</div></div>
  <div class="card"><div class="label">WebSocket</div><div id="ws" class="value">—</div><div id="wssub" class="sub">—</div></div>
</section>

<details class="card" style="margin-top:20px">
<summary style="cursor:pointer;font-weight:850;color:#bdc9dd;letter-spacing:.08em;text-transform:uppercase;font-size:11px">Risk & execution details</summary>
<section class="two-even" style="margin-top:12px">
  <div class="card">
    <div class="label">Actieve policy</div>
    <div class="metric"><span>Max daily loss</span><b id="riskdaily">—</b></div>
    <div class="metric"><span>Max drawdown</span><b id="riskdd">—</b></div>
    <div class="metric"><span>Max single trade</span><b id="risksingle">—</b></div>
    <div class="metric"><span>Cash reserve</span><b id="riskreserve">—</b></div>
    <div class="metric"><span>Current drawdown</span><b id="currentdd">—</b></div>
    <div class="metric"><span>Max entry nu</span><b id="maxentry">—</b></div>
  </div>
  <div class="card">
    <div class="label">Execution gates</div><div id="gatechips" class="gates"></div>
    <div class="metric"><span>Armed</span><b id="armed">—</b></div>
    <div class="metric"><span>Execution ready</span><b id="execready">—</b></div>
    <div class="metric"><span>Persisted live intent</span><b id="persisted">—</b></div>
    <div class="metric"><span>Portfolio isolated</span><b id="isolated">—</b></div>
    <div class="metric"><span>Runtime error</span><b id="runtimeerror">—</b></div>
  </div>
</section>
</details>

<div class="sectionhead"><h2>Agent balances</h2><i></i></div>
<section class="card"><div id="balances"></div></section>

<details class="card" style="margin-top:20px">
<summary style="cursor:pointer;font-weight:850;color:#bdc9dd;letter-spacing:.08em;text-transform:uppercase;font-size:11px">Technische execution-audit</summary>
<div class="tablewrap" style="margin-top:12px"><table class="table">
<thead><tr><th>Tijd</th><th>Actie</th><th>Product</th><th>Side</th><th>Waarde</th><th>Details</th></tr></thead>
<tbody id="audit"><tr><td colspan="6" class="subtitle">Audit laden…</td></tr></tbody>
</table></div>
</details>

<div class="foot"><span>Coinbase RiskTrader · dedicated isolated portfolio</span><span id="updated">—</span></div>
</div></div>

<script>
let token=sessionStorage.getItem("coinbase_dashboard_token")||"",apiKey=sessionStorage.getItem("coinbase_dashboard_api_key")||"";
const E=id=>document.getElementById(id);
const money=v=>Number(v||0).toLocaleString("nl-NL",{style:"currency",currency:"EUR",minimumFractionDigits:2,maximumFractionDigits:4});
const dec=(v,n=4)=>Number(v||0).toLocaleString("nl-NL",{maximumFractionDigits:n});
const pct=v=>Number(v||0).toLocaleString("nl-NL",{minimumFractionDigits:1,maximumFractionDigits:2})+"%";
const signedMoney=v=>(Number(v||0)>0?"+":"")+money(v);
const esc=v=>String(v??"—").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function set(id,v){E(id).textContent=v}
function headers(extra={}){const h={"Content-Type":"application/json",...extra};if(token)h.Authorization="Bearer "+token;if(apiKey)h["X-API-Key"]=apiKey;return h}
function showLogin(msg=""){E("app").classList.add("hidden");E("login").classList.remove("hidden");E("loginerr").textContent=msg}
async function api(path,opt={}){const r=await fetch(path,{...opt,headers:headers(opt.headers||{})});let d={};try{d=await r.json()}catch{}if(r.status===401){token="";apiKey="";sessionStorage.clear();showLogin("Sessie verlopen of API-key ongeldig.");throw new Error("Unauthorized")}if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail||d));return d}
async function login(){E("loginerr").textContent="";apiKey=E("apikey").value.trim();try{if(apiKey)sessionStorage.setItem("coinbase_dashboard_api_key",apiKey);else{const d=await api("/api/auth/login",{method:"POST",body:JSON.stringify({username:E("username").value,password:E("password").value})});token=d.access_token;sessionStorage.setItem("coinbase_dashboard_token",token)}E("login").classList.add("hidden");E("app").classList.remove("hidden");await refresh();window.dashboardTimer=setInterval(refresh,5000)}catch(e){E("loginerr").textContent=e.message}}
function logout(){sessionStorage.clear();location.reload()}

function pairTrades(audit){
  const rows=(Array.isArray(audit)?audit:[]).slice().sort((a,b)=>Number(a.at||0)-Number(b.at||0));
  const opens={},trades=[];
  for(const r of rows){
    if(r.action==="ENTRY_FILLED"){
      opens[String(r.product_id||"UNKNOWN")]={...r};
    }
    if(r.action==="EXIT_FILLED"){
      const p=String(r.product_id||"UNKNOWN"),en=opens[p]||{};
      const entryFee=Number(en.fees_eur||0),exitFee=Number(r.fees_eur||0),net=Number(r.realized_pnl_eur||0);
      trades.push({
        at:Number(r.at||0),product:p,risk:en.risk_tier||"—",
        entry:Number(en.price||0),exit:Number(r.price||0),
        fees:entryFee+exitFee,pnl:net,gross:net+entryFee+exitFee,
        reason:r.exit_reason||r.reason||"—",entryAt:Number(en.at||0),
        entryType:en.order_type||"—",exitType:r.order_type||"—"
      });
      delete opens[p];
    }
  }
  return trades;
}
function journalRows(trades){
  if(!trades.length)return '<tr><td colspan="8" class="subtitle">Nog geen gesloten strategy-trades in de lokale audit.</td></tr>';
  return trades.slice().reverse().map(t=>{
    const cls=t.pnl>=0?"green":"red";
    return '<tr><td class="mono">'+new Date(t.at*1000).toLocaleString("nl-NL",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})+'</td>'+
    '<td><b>'+esc(t.product)+'</b></td><td>'+esc(t.risk)+'</td>'+
    '<td class="mono">'+dec(t.entry,8)+'</td><td class="mono">'+dec(t.exit,8)+'</td>'+
    '<td class="mono">'+money(t.fees)+'</td><td class="mono result '+cls+'">'+signedMoney(t.pnl)+'</td>'+
    '<td><span class="reason">'+esc(t.reason)+'</span></td></tr>'
  }).join("");
}
function drawPnl(trades){
  if(!trades.length){E("pnlchart").innerHTML='<div class="chart-empty">Nog geen gesloten trades in de lokale audit.</div>';return}
  let cum=0;const pts=trades.map((t,i)=>({i:i+1,v:(cum+=t.pnl)}));
  const vals=pts.map(x=>x.v).concat([0]),min=Math.min(...vals),max=Math.max(...vals),range=Math.max(.01,max-min);
  const W=900,H=150,pad=18;
  const x=i=>pad+(i/(Math.max(1,pts.length-1)))*(W-pad*2);
  const y=v=>H-pad-((v-min)/range)*(H-pad*2);
  const path=pts.map((p,i)=>(i?"L":"M")+x(i).toFixed(1)+" "+y(p.v).toFixed(1)).join(" ");
  const zero=y(0).toFixed(1);
  E("pnlchart").innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
    '<line x1="0" y1="'+zero+'" x2="'+W+'" y2="'+zero+'" stroke="#27405f" stroke-width="1"/>'+
    '<path d="'+path+'" fill="none" stroke="'+(cum>=0?"#39d39f":"#ff667a")+'" stroke-width="3" vector-effect="non-scaling-stroke"/>'+
    pts.map((p,i)=>'<circle cx="'+x(i)+'" cy="'+y(p.v)+'" r="4" fill="'+(p.v>=0?"#39d39f":"#ff667a")+'"/>').join("")+
    '</svg>';
}
function auditRows(rows){
  const list=(rows||[]).slice(-18).reverse();
  if(!list.length)return '<tr><td colspan="6" class="subtitle">Nog geen execution-events.</td></tr>';
  return list.map(r=>{
    const detail=r.exit_reason||r.reason||r.status||r.error||r.risk_tier||"—";
    const amt=r.realized_pnl_eur!=null?signedMoney(r.realized_pnl_eur):(r.quote_size??r.base_size??r.managed_cash_eur??"—");
    return '<tr><td class="mono">'+(r.at?new Date(Number(r.at)*1000).toLocaleTimeString("nl-NL"):"—")+'</td>'+
    '<td>'+esc(r.action||r.event)+'</td><td>'+esc(r.product_id||"—")+'</td><td>'+esc(r.side||"—")+'</td>'+
    '<td class="mono">'+esc(amt)+'</td><td>'+esc(detail)+'</td></tr>'
  }).join("")
}
function gates(failed){const all=["enabled","execution_mode_live","live_execution_approved","coinbase_adapter_installed","coinbase_live_trading","emergency_stop_off","confirmation_present","runtime_armed","credentials_compatible","authenticated","isolated_portfolio_configured","daily_loss_stop_off","drawdown_stop_off","daily_risk_budget_sufficient","shadow_promotion_ready"];const f=new Set(failed||[]);return all.map(x=>'<span class="gate '+(f.has(x)?"fail":"")+'">'+(f.has(x)?"WAIT ":"OK ")+x+'</span>').join("")}

async function refresh(){
  try{
    const d=await api("/api/coinbase/dashboard/snapshot"),a=d.autonomous||{},r=d.readiness||{},o=d.opportunity||{},rt=d.realtime_orderflow||o.realtime||{},b=d.balances||{};
    const rd=r||a.readiness||{},targets=a.daily_targets||{},rules=a.hard_rules||{},audit=a.order_audit||[],tr=pairTrades(audit);
    const dayKey=new Date().toLocaleDateString("sv-SE",{timeZone:"Europe/Amsterdam"});
    const todayTrades=tr.filter(x=>new Date(Number(x.at||0)*1000).toLocaleDateString("sv-SE",{timeZone:"Europe/Amsterdam"})===dayKey);
    const pnl=Number(targets.profit_eur??a.day_pnl_eur??0),wins=todayTrades.filter(x=>x.pnl>0).length,losses=todayTrades.filter(x=>x.pnl<0).length;
    const fees=todayTrades.reduce((sum,x)=>sum+x.fees,0),gross=todayTrades.reduce((sum,x)=>sum+x.gross,0),net=todayTrades.reduce((sum,x)=>sum+x.pnl,0);
    const directAssets=Array.isArray(b.assets)?b.assets:[];
    const assetValue=(ccy)=>{
      const row=directAssets.find(x=>String(x.currency||"").toUpperCase()===ccy);
      if(row)return Number(row.available??row.total??0)||0;
      return Number((rd.balances||{})[ccy]||0)||0;
    };
    const usdcBal=assetValue("USDC"),eurBal=assetValue("EUR");

    set("nav",money(rd.portfolio_nav_eur||0));set("navsub",dec(usdcBal,4)+" USDC + "+money(eurBal)+" · isolated Agent-portfolio");
    set("daypnl",signedMoney(pnl));E("daypnl").className="value "+(pnl>=0?"green":"red");
    const wr=(wins+losses)?wins/(wins+losses)*100:0;
    set("daypnlsub",todayTrades.length+" gesloten trades vandaag · "+wins+" winst / "+losses+" verlies · "+pct(wr)+" winrate");
    set("trades",dec(usdcBal,4)+" USDC");set("tradesub","beschikbaar voor nieuwe USDC-markten");
    set("todaywinrate",money(eurBal));set("winsub","beschikbaar in EUR");

    const pending=a.pending_order||null,pos=a.managed_position||null;
    let exposure=0,phase="SCANNING",prod="—",side="—",otype="—",risk=(a.entry_diagnostics||{}).selected_risk_tier||"—",activitySub="Zoekt continu naar de beste Coinbase spot-kans.";
    if(pos){phase="POSITIE OPEN";prod=pos.product_id||"—";side="LONG";otype="managed";exposure=Number(pos.base_size||0)*Number(pos.entry_price||0);activitySub="Positie wordt bewaakt op stop-loss, take-profit, trailing en signal horizon."}
    if(pending){phase=pending.purpose==="exit"?"EXIT ORDER":pending.purpose==="entry"?"ENTRY ORDER":"ORDER OPEN";prod=pending.product_id||prod;side=pending.side||side;otype=pending.order_type||"—";exposure=Number(pending.quote_size||0)||exposure;activitySub="Order staat bij Coinbase en wordt automatisch bewaakt, herprijsd of naar fallback gestuurd."}
    set("exposure",phase);set("exposuresub",(prod!=="—"?prod+" · ":"")+(exposure?money(exposure)+" exposure":"geen open exposure"));
    set("activitytitle",phase);set("activitysub",activitySub);set("activitytag",a.coinbase_armed?"LIVE":"OFF");
    set("activityproduct","product "+prod);set("activityside","side "+side);set("activitytype","type "+otype);set("activityrisk","risk "+risk);
    const lastEvent=audit.length?audit[audit.length-1]:{};
    const lastEventHtml='<div class="metric"><span>Laatste actie</span><b>'+esc(lastEvent.action||lastEvent.event||"—")+'</b></div>'+
      '<div class="metric"><span>Laatste product</span><b>'+esc(lastEvent.product_id||"—")+'</b></div>'+
      '<div class="metric"><span>Tijd</span><b>'+(lastEvent.at?new Date(Number(lastEvent.at)*1000).toLocaleTimeString("nl-NL"):"—")+'</b></div>';
    E("currentmetrics").innerHTML=(pos?
      '<div class="metric"><span>Entry price</span><b>'+dec(pos.entry_price,8)+'</b></div><div class="metric"><span>Size</span><b>'+dec(pos.base_size,8)+'</b></div><div class="metric"><span>Opened</span><b>'+(pos.opened_at?new Date(Number(pos.opened_at)*1000).toLocaleTimeString("nl-NL"):"—")+'</b></div>':
      pending?'<div class="metric"><span>Order product</span><b>'+esc(pending.product_id)+'</b></div><div class="metric"><span>Order side</span><b>'+esc(pending.side)+'</b></div><div class="metric"><span>Order type</span><b>'+esc(pending.order_type||"—")+'</b></div>':
      '<div class="metric"><span>State</span><b>Geen open positie/order · scanner zoekt verder</b></div>')+lastEventHtml;

    set("grosspnl",signedMoney(gross));E("grosspnl").className=gross>=0?"green":"red";
    set("fees","-"+money(fees));E("fees").className="amber";set("netpnl",signedMoney(net));E("netpnl").className=net>=0?"green":"red";
    let insight="Er zijn nog onvoldoende gesloten trades om een verliesanalyse te maken.";
    if(tr.length){
      const feeShare=Math.abs(net)>0?fees/Math.abs(net)*100:0;
      if(net<0&&gross<0)insight="<strong>Hoofdoorzaak:</strong> de prijsbewegingen van gesloten trades waren negatief. Fees maakten het verlies groter. Totaal fees: <strong>"+money(fees)+"</strong>.";
      else if(net<0&&gross>=0)insight="<strong>Hoofdoorzaak:</strong> vóór fees waren de trades ongeveer positief, maar kosten draaiden het netto resultaat negatief. Fees: <strong>"+money(fees)+"</strong>.";
      else if(net>=0)insight="<strong>Netto positief.</strong> Bruto trading-resultaat "+signedMoney(gross)+" en fees "+money(fees)+".";
      insight+=" Gesloten trades vandaag: <strong>"+todayTrades.length+"</strong>.";
    }
    E("lossinsight").innerHTML=insight;
    E("journal").innerHTML=journalRows(tr);set("journalcount",tr.length+" gesloten trades totaal");drawPnl(todayTrades);

    const ed=a.entry_diagnostics||{},top=(o.top_candidates||[])[0]||{};
    set("scanned",o.scanned_markets??0);set("eligible",(o.eligible_scan_markets??o.tradable_markets??0)+" eligible · "+(o.fundable_markets??0)+" nu fundable");
    set("signals",ed.decisions_seen??0);set("routes",(ed.routes_considered??0)+" routes onderzocht · "+(ed.accepted_routes??0)+" accepted");
    set("candidate",top.product_id||ed.best_after_cost_product||"—");set("candidateedge",(top.forecast_move_bps!=null?dec(top.forecast_move_bps,1)+" bps forecast":"")+(ed.best_after_cost_edge_bps!=null?" · "+dec(ed.best_after_cost_edge_bps,1)+" bps net edge":""));
    set("ws",rt.connected?"CONNECTED":"REST");E("ws").className="value "+(rt.connected?"green":"amber");set("wssub",(rt.subscribed_count??0)+" live products · "+(rt.last_error||"geen error"));

    set("riskdaily",pct(rules.max_daily_loss_pct));set("riskdd",pct(rules.max_drawdown_pct));set("risksingle",pct(rules.max_single_trade_pct));set("riskreserve",pct(rules.min_cash_reserve_pct));
    set("currentdd",pct(a.current_drawdown_pct));set("maxentry",money(rd.max_single_trade_eur||0));
    E("gatechips").innerHTML=gates(r.execution_failed_gates||r.failed_gates||[]);
    set("armed",a.coinbase_armed?"JA":"NEE");set("execready",r.execution_ready_now?"JA":"NEE");set("persisted",(r.arm_persistence||{}).persisted_armed?"JA":"NEE");set("isolated",b.portfolio_scoped?"JA":"NEE");set("runtimeerror",a.runtime_error||"GEEN");

    let assets=Array.isArray(b.assets)?b.assets:[];if(!assets.length){assets=["EUR","USDC","BTC"].map(ccy=>({currency:ccy,available:String(Number((rd.balances||{})[ccy]||0)),hold:"0",total:String(Number((rd.balances||{})[ccy]||0))})).filter(x=>Number(x.total)>0)}E("balances").innerHTML=assets.length?assets.map(x=>'<div class="metric"><span>'+esc(x.currency)+'</span><b>'+esc(x.available)+' beschikbaar · '+esc(x.hold)+' hold · '+esc(x.total)+' totaal</b></div>').join(""):'<div class="subtitle">Saldo tijdelijk niet beschikbaar; trading/scanner blijft actief.</div>';
    E("audit").innerHTML=auditRows(audit);

    const armed=!!a.coinbase_armed,ready=!!r.execution_ready_now;E("statusdot").className="dot "+(armed?"":"off");set("topstatus",armed?"COINBASE LIVE":"COINBASE OFF");set("readytag",ready?"EXECUTION READY":"GATED");
    E("livebtn").disabled=armed;E("livebtn").title=armed?"Coinbase RiskTrader is al live":(r.ready_to_arm?"Alle gates gereed":"Klik om live-check uit te voeren en blocker te tonen");E("stopbtn").classList.toggle("hidden",!armed);
    let msg=armed?(ready?"RiskTrader is live en execution-ready.":"RiskTrader is live maar wacht op: "+(r.execution_failed_gates||[]).join(", ")):"Live execution staat uit.";
    E("notice").textContent=msg;E("notice").className="notice "+(!ready?"warn":"");
    set("updated","Bijgewerkt "+new Date().toLocaleTimeString("nl-NL"));
  }catch(e){E("notice").textContent="Dashboard update mislukt: "+e.message;E("notice").className="notice bad"}
}
async function activateLive(){try{if(!confirm("Coinbase RiskTrader live activeren? De agent mag daarna echte spot-orders plaatsen binnen het geïsoleerde Agent-portfolio."))return;await api("/api/coinbase/live/activate",{method:"POST",body:JSON.stringify({confirmation:"I_UNDERSTAND_COINBASE_LIVE_ORDERS"})});await refresh()}catch(e){E("notice").textContent="Live niet geactiveerd: "+e.message;E("notice").className="notice bad";alert("Live niet geactiveerd: "+e.message)}}
async function deactivateLive(){try{if(!confirm("Live trading stoppen? Open posities/orders blijven door Coinbase bestaan totdat de runtime ze verder afhandelt."))return;await api("/api/coinbase/live/deactivate",{method:"POST",body:"{}"});await refresh()}catch(e){E("notice").textContent="Live niet gestopt: "+e.message;E("notice").className="notice bad";alert("Live niet gestopt: "+e.message)}}
async function boot(){if(apiKey||token){E("login").classList.add("hidden");E("app").classList.remove("hidden");try{await refresh();window.dashboardTimer=setInterval(refresh,5000);return}catch{}}showLogin("")}boot();
</script>
</body></html>'''


def coinbase_dashboard_html() -> str:
    return COINBASE_DASHBOARD_HTML
