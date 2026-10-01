"""HTML dashboard for the protected AutoTrader paper/live-readiness API."""

from __future__ import annotations


DASHBOARD_HTML = r'''<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AutoTrader | Portfolio Control Room</title>
<style>
:root{--bg:#07111f;--panel:#101e31;--panel2:#14263d;--line:#243954;--text:#e8f0fa;--muted:#8ea4bd;--green:#35d49a;--amber:#f5bd4f;--red:#ff6b7a;--blue:#61a7ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#17345d 0,#07111f 42%);font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--text);min-height:100vh}
.wrap{max-width:1380px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:center;gap:18px;margin-bottom:26px}.brand{display:flex;gap:14px;align-items:center}.logo{width:46px;height:46px;border-radius:14px;background:linear-gradient(135deg,#35d49a,#4386ff);display:grid;place-items:center;font-weight:900;color:#06101c}.eyebrow{color:var(--green);font-size:12px;text-transform:uppercase;letter-spacing:.14em;font-weight:800}.title{font-size:30px;font-weight:800;margin:3px 0}.sub{color:var(--muted);font-size:13px}.pill{border:1px solid var(--line);border-radius:999px;padding:9px 13px;color:var(--muted);font-size:12px}.pill b{color:var(--green)}
.login{max-width:430px;margin:10vh auto;background:rgba(16,30,49,.92);border:1px solid var(--line);border-radius:22px;padding:28px;box-shadow:0 24px 80px #0008}.login h1{margin-top:0}.field{display:grid;gap:7px;margin:14px 0}.field label{font-size:12px;color:var(--muted)}input{width:100%;background:#091728;border:1px solid var(--line);border-radius:10px;padding:12px;color:var(--text);outline:none}input:focus{border-color:var(--blue)}button{border:0;border-radius:10px;padding:11px 15px;font-weight:800;cursor:pointer;background:var(--green);color:#04131b}button.secondary{background:var(--panel2);color:var(--text);border:1px solid var(--line)}.err{color:var(--red);font-size:13px;min-height:20px;margin-top:10px}
.hidden{display:none!important}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:linear-gradient(145deg,rgba(20,38,61,.96),rgba(13,27,45,.96));border:1px solid var(--line);border-radius:17px;padding:19px;box-shadow:0 12px 35px #0002}.label{color:var(--muted);font-size:12px}.value{font-size:27px;font-weight:800;margin-top:8px}.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.blue{color:var(--blue)}.section{margin-top:20px}.section h2{font-size:16px;margin:0 0 11px}.two{display:grid;grid-template-columns:1.25fr .75fr;gap:14px}.table{width:100%;border-collapse:collapse;font-size:13px}.table th{text-align:left;color:var(--muted);font-weight:600;padding:10px 8px;border-bottom:1px solid var(--line)}.table td{padding:12px 8px;border-bottom:1px solid #1c3049}.status{display:inline-flex;align-items:center;gap:7px}.dot{width:8px;height:8px;border-radius:99px;background:var(--green);box-shadow:0 0 12px var(--green)}.dot.off{background:var(--red);box-shadow:0 0 12px var(--red)}.metric{display:flex;justify-content:space-between;border-bottom:1px solid #1c3049;padding:12px 0;color:var(--muted)}.metric b{color:var(--text)}.bar{height:9px;border-radius:99px;background:#091728;overflow:hidden;margin-top:8px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--blue));border-radius:inherit}.notice{border-left:3px solid var(--amber);background:#2c2514;padding:12px 14px;color:#ead9ad;font-size:13px;border-radius:8px}.foot{color:var(--muted);font-size:11px;margin-top:22px;display:flex;justify-content:space-between;gap:10px}
.section-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:26px 0 10px}.section-title h3{margin:0;font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted)}.section-title .line{height:1px;background:var(--line);flex:1}.badge{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:#0b1728;border-radius:999px;padding:5px 9px;font-size:11px;color:var(--muted)}.badge.ok{color:var(--green);border-color:#245e4d}.badge.live{color:var(--blue);border-color:#2e568a}.exchange-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.exchange-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.exchange-name{font-size:18px;font-weight:800}.mini{font-size:11px;color:var(--muted)}.asset-chip{display:inline-flex;padding:4px 8px;border:1px solid var(--line);border-radius:999px;font-size:11px;margin:2px 3px 2px 0;color:var(--muted)}.table.compact td,.table.compact th{padding:8px 7px}.muted-card{background:linear-gradient(145deg,rgba(11,23,40,.96),rgba(12,26,43,.96))}.hero-strip{display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px;margin-top:20px}.hero-strip .card{min-height:106px}.hero-label{font-size:11px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted)}.hero-value{font-size:24px;font-weight:850;margin-top:7px}
.control-card{background:linear-gradient(145deg,rgba(18,38,62,.98),rgba(8,20,35,.98));border:1px solid #2b4565;box-shadow:0 18px 50px #0004}
.control-head{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:15px}.control-title{font-size:20px;font-weight:850}.control-sub{font-size:12px;color:var(--muted);margin-top:4px}
.order-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0 16px}.order-kpi{padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:#0a1728}.order-kpi .k{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}.order-kpi .v{font-size:20px;font-weight:850;margin-top:5px}
.order-layout{display:grid;grid-template-columns:.85fr 1.65fr;gap:14px}.table-wrap{overflow:auto;max-height:430px;border:1px solid #1f344e;border-radius:12px}.table-wrap .table{min-width:720px}.table-wrap thead th{position:sticky;top:0;background:#102038;z-index:2}
.status-chip{display:inline-flex;align-items:center;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;border:1px solid var(--line)}.status-chip.open{color:var(--blue);border-color:#315e92;background:#102945}.status-chip.filled{color:var(--green);border-color:#24604e;background:#0e2b25}.status-chip.canceled,.status-chip.cancelled,.status-chip.expired{color:var(--muted);background:#111d2d}.status-chip.rejected,.status-chip.error,.status-chip.blocked{color:var(--red);border-color:#743442;background:#31151d}
.side-buy{color:var(--green);font-weight:850}.side-sell{color:var(--amber);font-weight:850}.mono{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.top-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
@media(max-width:1050px){.order-layout{grid-template-columns:1fr}.order-kpis{grid-template-columns:repeat(2,1fr)}}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.two,.exchange-grid,.hero-strip{grid-template-columns:1fr}}@media(max-width:560px){.wrap{padding:16px}.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
</style></head><body>
<div id="login" class="login"><div class="eyebrow">Private control room</div><h1>AutoTrader dashboard</h1><p class="sub">Meld aan om portfolio- en positiedata te bekijken. Er worden geen orders vanuit dit dashboard geplaatst.</p><div class="field"><label>Gebruikersnaam</label><input id="username" autocomplete="username" value="admin"></div><div class="field"><label>Wachtwoord</label><input id="password" type="password" autocomplete="current-password"></div><div class="field"><label>Of API-key</label><input id="apikey" type="password" autocomplete="off" placeholder="X-API-Key (optioneel)"></div><button onclick="login()">Dashboard openen</button><div id="loginerr" class="err"></div></div>
<div id="app" class="hidden"><div class="wrap"><header class="top"><div class="brand"><div class="logo">AT</div><div><div class="eyebrow">Portfolio control room</div><div class="title">AutoTrader</div><div class="sub">Bitvavo monitoring · live updates · beveiligde sessie</div></div></div><div class="top-actions"><span class="pill">Mode: <b id="mode">paper</b></span><button class="secondary" onclick="refresh()">Vernieuwen</button><button id="livebtn" onclick="activateLive()" disabled>Live Trading</button><button class="secondary" onclick="logout()">Uitloggen</button></div></header>
<div id="notice" class="notice">Live Trading blijft fail-closed. De knop wordt alleen actief wanneer alle server-side gates en Bitvavo-credentials aantoonbaar klaarstaan.</div><div class="hero-strip"><div class="card"><div class="hero-label">Systeemstatus</div><div class="hero-value"><span id="systemstatus" class="green">ONLINE</span></div><div class="sub">Bitvavo + Coinbase connectivity, risk gates en learning runtime</div></div><div class="card"><div class="hero-label">Coinbase API</div><div id="coinbasehero" class="hero-value">—</div><div class="sub">Authenticated Advanced Trade</div></div><div class="card"><div class="hero-label">Arbitrage scanner</div><div id="arbhero" class="hero-value">—</div><div class="sub">Shadow · netto edge na kosten</div></div></div>
<section class="section"><div class="card" style="margin-bottom:14px"><h2>Live Trading</h2><div class="metric"><span>Readiness</span><b id="liveready">controleren…</b></div><div id="livecheck" class="sub" style="margin-top:10px">Geen live orders worden geplaatst door deze statuscontrole.</div><div style="margin-top:12px"><button class="secondary" onclick="groupStrategyControl('start-live')">Start alle live bots</button><button class="secondary" onclick="groupStrategyControl('stop-live')" style="margin-left:8px">Stop alle live bots</button><button id="liveaction" onclick="activateLive()" disabled style="margin-left:8px">Live Trading activeren</button><button id="livestop" class="secondary" onclick="deactivateLive()" style="display:none;margin-left:8px">Stop Live Trading</button></div></div></section>
<section class="section"><div class="grid"><div class="card"><div id="eurlabel" class="label">Portfolio waarde EUR</div><div id="eur" class="value">—</div><div id="eurdelta" class="sub">—</div></div><div class="card"><div id="btclabel" class="label">Portfolio waarde BTC</div><div id="btc" class="value blue">—</div><div id="btcrate" class="sub">—</div></div><div class="card"><div class="label">PnL</div><div id="pnl" class="value">—</div><div id="pnlpct" class="sub">—</div></div><div class="card"><div class="label">Drawdown</div><div id="dd" class="value amber">—</div><div class="sub">Vanaf lokale equity-piek</div></div></div></section>
<section class="section"><div class="card control-card"><div class="control-head"><div><div class="eyebrow">Execution monitor</div><div class="control-title">Order Control Center</div><div class="control-sub">Direct zicht op open Bitvavo-orders én iedere recente bot-order uit het duurzame journal.</div></div><span class="badge live">READ ONLY · AUTO REFRESH</span></div><div class="order-kpis"><div class="order-kpi"><div class="k">Nu open</div><div id="orderOpenCount" class="v blue">0</div></div><div class="order-kpi"><div class="k">Recent gevuld</div><div id="orderFilledCount" class="v green">0</div></div><div class="order-kpi"><div class="k">Geannuleerd</div><div id="orderCanceledCount" class="v">0</div></div><div class="order-kpi"><div class="k">Rejected / error</div><div id="orderErrorCount" class="v red">0</div></div></div><div class="order-layout"><div><div class="exchange-head"><div><div class="exchange-name">Open orders</div><div class="mini">Rechtstreeks van Bitvavo</div></div><span id="openOrderBadge" class="badge">0 open</span></div><div class="table-wrap"><table class="table compact"><thead><tr><th>Markt</th><th>Side</th><th>Qty</th><th>Prijs</th><th>Waarde</th><th>Status</th></tr></thead><tbody id="liveorders"><tr><td colspan="6" class="sub">Laden…</td></tr></tbody></table></div><div id="liveordersnote" class="sub" style="margin-top:9px">Read-only uit Bitvavo.</div></div><div><div class="exchange-head"><div><div class="exchange-name">Alle recente orders</div><div class="mini">Nieuwste eerst · order-ID's en secrets bewust verborgen</div></div><span id="activityBadge" class="badge ok">journal</span></div><div class="table-wrap"><table class="table compact"><thead><tr><th>Tijd</th><th>Bot</th><th>Markt</th><th>Side</th><th>Type</th><th>Qty</th><th>Prijs</th><th>Fills</th><th>Status</th></tr></thead><tbody id="orderactivity"><tr><td colspan="9" class="sub">Orderhistorie laden…</td></tr></tbody></table></div><div id="orderactivitynote" class="sub" style="margin-top:9px">Duurzame journal-history.</div></div></div></div></section>
<section class="section two"><div class="card"><h2>Open posities</h2><table class="table"><thead><tr><th>Symbool</th><th>Side</th><th>Notional</th><th>PnL</th></tr></thead><tbody id="positions"><tr><td colspan="4" class="sub">Laden…</td></tr></tbody></table></div><div class="card"><h2>Execution & risk</h2><div class="metric"><span>Status</span><b id="execmode">—</b></div><div class="metric"><span>Dagelijkse exposure</span><b id="exposure">—</b></div><div class="metric"><span>Dagverlies</span><b id="loss">—</b></div><div class="metric"><span>Max per order</span><b id="maxtrade">—</b></div><div class="metric"><span>Max dagexposure</span><b id="maxdaily">—</b></div><div class="metric"><span>Max dagverlies</span><b id="maxloss">—</b></div></div></section>
<section class="section"><div class="card"><h2>Profit supervisor</h2><div class="grid" style="margin-bottom:12px"><div><div class="label">Economische PnL</div><div id="profitEconomic" class="value">—</div></div><div><div class="label">Gerealiseerd netto</div><div id="profitRealized" class="value">—</div></div><div><div class="label">Ongerealiseerd na exit-kosten</div><div id="profitUnrealized" class="value">—</div></div><div><div class="label">Min. edge nieuwe entry</div><div id="profitEdge" class="value">—</div></div></div><table class="table"><thead><tr><th>Bot</th><th>Markt</th><th>Status</th><th>Inventory</th><th>Break-even</th><th>Min winst-exit</th><th>Net PnL</th></tr></thead><tbody id="profitrows"><tr><td colspan="7" class="sub">Laden…</td></tr></tbody></table><div class="sub" style="margin-top:10px">Gebaseerd op echte journal-fills en geschatte toekomstige fee/slippage. Geen winstgarantie.</div></div></section>
<section class="section two"><div class="card"><h2>Strategieën</h2><table class="table"><thead><tr><th>Naam</th><th>Status</th><th>PnL</th><th>Trades</th></tr></thead><tbody id="strategies"><tr><td colspan="4" class="sub">Laden…</td></tr></tbody></table></div><div class="card"><h2>Runtime</h2><div class="metric"><span>Feed/ticker</span><b id="ticker">—</b></div><div class="metric"><span>Laatste update</span><b id="updated">—</b></div><div class="metric"><span>WebSocket</span><b id="socket">verbinden…</b></div><div class="bar"><i id="healthbar" style="width:0%"></i></div><div class="sub" style="margin-top:8px">Gezondheidsindicator op basis van ticker en laatste fout.</div></div></section>
<section class="section two"><div class="card"><h2>Live Market Universe</h2><table class="table"><thead><tr><th>Markt</th><th>Venue</th><th>Feed</th><th>Agents</th><th>Orders</th></tr></thead><tbody id="markets"><tr><td colspan="5" class="sub">Laden…</td></tr></tbody></table><div id="marketnote" class="sub" style="margin-top:10px">Vetted markten + 60-market scanner; uitvoering alleen na alle strategy- en risk-gates.</div></div><div class="card"><h2>Trading agents</h2><div id="agents"><div class="sub">Laden…</div></div><div class="notice" style="margin-top:12px">Workflow: marktdata → strategie-signaal → risicocontrole → order-intentie → journal/PnL. Live execution blijft fail-closed tot alle gates én handmatige activatie gereed zijn.</div></div></section>
<div class="section-title"><h3>Profit Optimization v2</h3><div class="line"></div><span class="badge live">AUTONOMOUS AFTER ARM</span></div>
<section class="section exchange-grid">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Gezamenlijk botdoel</div><div class="mini">Alle bots dragen bij aan één portfolio-doel · nooit een reden om risico te verhogen</div></div><span id="goalbadge" class="badge">€25K TARGET</span></div>
    <div class="grid" style="margin-bottom:12px">
      <div><div class="label">Huidige equity-schatting</div><div id="goalcurrent" class="value">—</div></div>
      <div><div class="label">Doel</div><div id="goaltarget" class="value blue">€ 25.000</div></div>
      <div><div class="label">Voortgang</div><div id="goalprogress" class="value">—</div></div>
      <div><div class="label">Volgende mijlpaal</div><div id="goalnext" class="value amber">—</div></div>
    </div>
    <div class="bar"><i id="goalbar" style="width:0%"></i></div>
    <div id="goalnote" class="sub" style="margin-top:9px">Geen martingale, geen leverage- of budgetverhoging om het doel in te halen.</div>
  </div>
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">BTC Reference Feed</div><div class="mini">Binance public BTCUSDT · 1 seconde · read-only referentie</div></div><span id="binancebadge" class="badge ok">READ ONLY</span></div>
    <div class="metric"><span>BTCUSDT referentie</span><b id="binanceprice">—</b></div>
    <div class="metric"><span>Interval</span><b id="binanceinterval">—</b></div>
    <div class="metric"><span>Laatste update</span><b id="binanceupdated">—</b></div>
    <div id="binancenote" class="sub" style="margin-top:9px">Deze feed kan geen Binance-orders plaatsen.</div>
  </div>
</section>
<section class="section exchange-grid">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Execution v2</div><div class="mini">Maker-first advies voor stale orders · profit-guard actief</div></div><span id="execv2badge" class="badge">advisory</span></div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Bot</th><th>Markt</th><th>Leeftijd</th><th>Limiet</th><th>Maker target</th><th>Move</th><th>Advies</th></tr></thead><tbody id="execv2rows"><tr><td colspan="7" class="sub">Execution v2 laden…</td></tr></tbody></table></div>
    <div id="execv2note" class="sub" style="margin-top:9px">Analyseert alleen; annuleert of vervangt geen live orders.</div>
  </div>
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">50+ Market Opportunity Router</div><div class="mini">Live EUR-markten op spread, liquiditeit, momentum en volatiliteit</div></div><span id="routerbadge" class="badge ok">SCANNING</span></div>
    <div class="order-kpis" style="grid-template-columns:repeat(4,1fr);margin-top:8px">
      <div class="order-kpi"><div class="k">Geconfigureerd</div><div id="routerconfigured" class="v blue">—</div></div>
      <div class="order-kpi"><div class="k">Nu gescand</div><div id="routerscanned" class="v green">—</div></div>
      <div class="order-kpi"><div class="k">Doel scanner</div><div id="routertarget" class="v">60</div></div>
      <div class="order-kpi"><div class="k">Fouten</div><div id="routererrors" class="v">0</div></div>
    </div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Strategie</th><th>Beste markt</th><th>Score</th><th>Spread</th><th>Momentum</th><th>Liquiditeit</th></tr></thead><tbody id="routerrows"><tr><td colspan="6" class="sub">Opportunity Router laden…</td></tr></tbody></table></div>
    <div id="routernote" class="sub" style="margin-top:9px">Read-only multi-market scan.</div>
  </div>
</section>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Fee Efficiency</div><div class="mini">Netto PnL per bot na gemeten fees · fee-drag zichtbaar</div></div><span id="feebadge" class="badge">metrics</span></div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Bot</th><th>Markt</th><th>Netto PnL</th><th>Fees</th><th>Fee drag</th><th>Net / exit</th><th>Status</th></tr></thead><tbody id="feerows"><tr><td colspan="7" class="sub">Fee-efficiency laden…</td></tr></tbody></table></div>
    <div id="feenote" class="sub" style="margin-top:9px">Allocator v2 gebruikt deze metrics alleen als advies; live-budgetten worden niet automatisch gewijzigd.</div>
  </div>
</section>
<div class="section-title"><h3>Autonomous Control Loop</h3><div class="line"></div><span id="autonomybadge" class="badge">SET → EXECUTE → LEARN → REPEAT</span></div>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Autonomous Decision Engine</div><div class="mini">Na operator-arm kiest het systeem zelf markt + ordergrootte binnen harde caps</div></div><span id="autonomymode" class="badge">controleren</span></div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Agent</th><th>Huidige markt</th><th>Gewenste markt</th><th>Live opties</th><th>Score</th><th>Confidence</th><th>Order €</th><th>Switch</th><th>Reden</th></tr></thead><tbody id="autonomyrows"><tr><td colspan="9" class="sub">Autonomy laden…</td></tr></tbody></table></div>
    <div id="autonomynote" class="sub" style="margin-top:9px">De engine kan zichzelf nooit armen en mag budget/leverage/harde risicolimieten niet verhogen.</div>
  </div>
</section>
<div class="section-title"><h3>Risk Lab</h3><div class="line"></div><span class="badge">PAPER ONLY</span></div>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Leverage + Capped Martingale Lab</div><div class="mini">Meet rendement en drawdown vóór enige aparte live-goedkeuring</div></div><span id="risklabbadge" class="badge">SHADOW RISK LAB</span></div>
    <div class="order-kpis">
      <div class="order-kpi"><div class="k">Leverage</div><div id="risklableverage" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Huidige inzet</div><div id="risklabstake" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Net PnL</div><div id="risklabpnl" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Max drawdown</div><div id="risklabdd" class="v">—</div></div>
    </div>
    <div id="risklabnote" class="sub">Deze bot kan geen live orders sturen.</div>
  </div>
</section>
<div class="section-title"><h3>Futures + Trading AI Lab</h3><div class="line"></div><span class="badge">SHADOW ONLY</span></div>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Perpetual AI Research</div><div class="mini">Public perp data · long/short simulation · funding/basis + online ML · geen extra Railway-service</div></div><span id="futuresaibadge" class="badge">laden</span></div>
    <div style="overflow-x:auto"><table class="table compact"><thead><tr><th>Markt</th><th>Mark</th><th>Funding</th><th>AI up</th><th>Confidence</th><th>Signaal</th><th>Positie</th><th>Trades</th><th>Net PnL</th><th>DD</th><th>Review</th></tr></thead><tbody id="futuresairows"><tr><td colspan="11" class="sub">Futures AI laden…</td></tr></tbody></table></div>
    <div id="futuresainote" class="sub" style="margin-top:10px">Shadow futures: geen credentials, leverage-execution of echte orders.</div>
  </div>
</section>
<div class="section-title"><h3>Shadow Alpha Lab</h3><div class="line"></div><span class="badge">NO LIVE ORDERS</span></div>
<section class="section exchange-grid"><div class="card"><div class="exchange-head"><div><div class="exchange-name">Shadow Strategy Scorecard</div><div class="mini">Live marketdata · simulated fills · fees/slippage included · operator approval required</div></div><span id="shadowbadge" class="badge">shadow</span></div><div style="overflow-x:auto"><table class="table compact"><thead><tr><th>Bot</th><th>Markt</th><th>Trades</th><th>W/L</th><th>Winrate</th><th>Net PnL</th><th>DD</th><th>Positie</th><th>Score</th><th>Status</th><th>Signaal</th></tr></thead><tbody id="shadowrows"><tr><td colspan="11" class="sub">Shadow bots laden…</td></tr></tbody></table></div><div id="shadownote" class="sub" style="margin-top:10px">Deze bots mogen geen echte orders plaatsen.</div></div><div class="card"><div class="exchange-head"><div><div class="exchange-name">Strategy Allocator v2</div><div class="mini">Performance-weighted advies binnen hetzelfde totaalbudget</div></div><span id="allocatorbadge" class="badge">advisory</span></div><table class="table compact"><thead><tr><th>Strategie</th><th>Mode</th><th>Samples</th><th>Score</th><th>Basis</th><th>Advies</th></tr></thead><tbody id="allocatorrows"><tr><td colspan="6" class="sub">Allocator laden…</td></tr></tbody></table><div id="allocatornote" class="sub" style="margin-top:10px">Live allocaties worden niet automatisch gewijzigd.</div></div></section>
<div class="section-title"><h3>Exchange connectivity & balances</h3><div class="line"></div><span class="badge live">LIVE DATA</span></div>
<section class="section exchange-grid"><div class="card"><div class="exchange-head"><div><div class="exchange-name">Coinbase Advanced</div><div class="mini">Authenticated read-only balance view</div></div><span id="coinbasebadge" class="badge">controleren</span></div><div class="metric"><span>Authenticatie</span><b id="coinbaseauth">—</b></div><div class="metric"><span>API-status</span><b id="coinbasestatus">—</b></div><div class="metric"><span>Accounts</span><b id="coinbaseaccounts">—</b></div><div class="metric"><span>Assets met saldo</span><b id="coinbaseassetcount">—</b></div><table class="table compact" style="margin-top:10px"><thead><tr><th>Asset</th><th>Beschikbaar</th><th>Hold</th><th>Totaal</th></tr></thead><tbody id="coinbaseassets"><tr><td colspan="4" class="sub">Coinbase saldo laden…</td></tr></tbody></table><div id="coinbasenote" class="sub" style="margin-top:10px">Geen account-ID's of API-secrets worden weergegeven.</div></div><div class="card"><div class="exchange-head"><div><div class="exchange-name">Coinbase ↔ Bitvavo arbitrage</div><div class="mini">Executable top-of-book shadow scan</div></div><span id="arbbadge" class="badge">shadow</span></div><div class="metric"><span>Scanner</span><b id="arbmode">—</b></div><div class="metric"><span>Laatste scan</span><b id="arbchecked">—</b></div><table class="table compact"><thead><tr><th>Markt</th><th>Koop</th><th>Verkoop</th><th>Bruto</th><th>Netto</th><th>Status</th></tr></thead><tbody id="arbrows"><tr><td colspan="6" class="sub">Scanner laden…</td></tr></tbody></table><div id="arbnote" class="sub" style="margin-top:10px">Shadow scanner: analyseert alleen; verstuurt geen Coinbase-orders.</div></div></section>
<section class="section two"><div class="card"><h2>Bitvavo</h2><div class="metric"><span>Credentials aanwezig</span><b id="fusioncred">—</b></div><div class="metric"><span>Read-only authenticatie</span><b id="fusionauth">—</b></div><div class="metric"><span>Balance endpoint</span><b id="fusionendpoint">—</b></div><div class="metric"><span>Bitvavo order mode</span><b id="fusionmode">—</b></div><div class="metric"><span>Laatste controle</span><b id="fusionchecked">—</b></div><div id="fusionnote" class="notice" style="margin-top:12px">Geen Bitvavo-status geladen.</div></div><div class="card"><h2>Safety gates</h2><div class="metric"><span>Global mode</span><b id="safetymode">—</b></div><div class="metric"><span>Live Bitvavo orders</span><b id="fusionlive">—</b></div><div class="metric"><span>Emergency stop</span><b id="emergencystop">—</b></div><div class="metric"><span>Withdrawal/Transfer</span><b class="green">Niet gebruikt</b></div><div class="sub" style="margin-top:12px">Deze kaart toont alleen statusmetadata. Het dashboard plaatst geen orders.</div></div></section>
<div class="foot"><span id="last">Nog niet bijgewerkt</span><span id="apierror" class="red"></span><span>Alle waarden zijn door de API aangeleverd.</span></div></div></div>
<script>
let token=sessionStorage.getItem('at_token')||'', apiKey='', socket;
const $=id=>document.getElementById(id); const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); const money=v=>v==null?'—':'€ '+Number(v).toFixed(2); const num=v=>v==null?'—':Number(v).toFixed(6);
function headers(){let h={'Accept':'application/json'};if(token)h.Authorization='Bearer '+token;if(apiKey)h['X-API-Key']=apiKey;return h}
async function get(path){let r=await fetch(path,{headers:headers()});if(r.status===401||r.status===503)throw Error('Sessie ongeldig of dashboard-auth ontbreekt');if(!r.ok)throw Error('API fout '+r.status);return r.json()}
async function login(){ $('loginerr').textContent=''; apiKey=$('apikey').value.trim(); if(apiKey){token='';}else{try{let r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value,password:$('password').value})});let d=await r.json();if(!r.ok)throw Error(d.detail||'Login mislukt');token=d.access_token;sessionStorage.setItem('at_token',token)}catch(e){$('loginerr').textContent=e.message;return}} $('login').classList.add('hidden');$('app').classList.remove('hidden');refresh();connect()}
function logout(){sessionStorage.removeItem('at_token');apiKey='';token='';location.reload()}
function renderReport(d){let a=d.account||{},p=d.pnl||{},b=d.balance||{},r=d.rates||{};$('eur').textContent=money(b.eur);$('btc').textContent=num(b.btc)+' BTC';$('pnl').textContent=money(p.eur);$('pnl').className='value '+(p.eur>=0?'green':'red');$('pnlpct').textContent=Number(a.pnl_pct||0).toFixed(2)+'% rendement';$('dd').textContent=Number(a.drawdown_pct||0).toFixed(2)+'%';$('eurdelta').textContent=money(p.usd)+' in USD';$('btcrate').textContent=r.btc_usd?'BTC/USD '+Number(r.btc_usd).toFixed(0):'BTC-koers niet beschikbaar'}
function renderExec(d){let l=d.limits||{};$('mode').textContent=d.mode||'paper';$('execmode').textContent=(d.mode||'paper')+' · '+(d.live_execution_capability||'onbekend');$('exposure').textContent='€ '+(d.daily_exposure_eur||'0');$('loss').textContent='€ '+(d.daily_loss_eur||'0');$('maxtrade').textContent='€ '+(l.max_trade_eur||'—');$('maxdaily').textContent='€ '+(l.max_daily_exposure_eur||'—');$('maxloss').textContent='€ '+(l.max_daily_loss_eur||'—')}
function renderStrategies(d){let rows=d.pnl_per_strategy||[];$('strategies').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(x.name)}</td><td><span class="status"><i class="dot ${x.status==='running'?'':'off'}"></i>${esc(x.status)}</span></td><td>${money(x.pnlAllTime)}</td><td>${esc(x.tradesToday??0)}</td></tr>`).join(''):'<tr><td colspan="4" class="sub">Geen strategieën</td></tr>'}
function renderMarkets(d){let rows=d.markets||[];$('markets').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.symbol)}</b></td><td>${esc(d.venue||'—')}</td><td><span class="status"><i class="dot off"></i>${esc(x.price_status||'onbekend')}</span></td><td>${esc((x.strategies||[]).join(', ')||'scanner')}</td><td>${d.orders_enabled?'ingeschakeld':'uit'}</td></tr>`).join(''):'<tr><td colspan="5" class="sub">Geen markten geconfigureerd</td></tr>';$('marketnote').textContent=(d.router_scanned||0)+'/'+(d.router_configured||0)+' markten gescand · '+rows.length+' vetted live-opties zichtbaar.'}
function renderAgents(d){let names={market_maker:'Market maker · passieve spread',arbitrage:'Arbitrage hunter · prijsverschil',grid:'Grid runner · inventory grid',sniper:'Sniper bot · momentum'};let rows=d.strategies||[];$('agents').innerHTML=rows.length?rows.map(x=>{let arb=x.name==='arbitrage',label=x.running?'actief':(arb?'shadow gereed':'gestopt'),cls=x.running?'green':(arb?'blue':'amber'),id=arb?' id="arbAgentState"':'';return `<div class="metric"><span>${esc(names[x.name]||x.name)}<small class="sub"> · ${x.live_capable?'live':'shadow'} · €${Number(x.allocation_eur||0).toFixed(0)}</small></span><b${id} class="${cls}">${label}</b></div>`}).join(''):'<div class="sub">Geen agents geregistreerd</div>'}
function renderCoinbase(d){
 let ok=d.authenticated===true;
 $('coinbaseauth').textContent=ok?'geslaagd':'mislukt';
 $('coinbaseauth').className=ok?'green':'red';
 $('coinbasestatus').textContent=d.status?('HTTP '+d.status):(ok?'200':'—');
 $('coinbasestatus').className=ok?'green':'amber';
 $('coinbasehero').textContent=ok?'CONNECTED':'OFFLINE';
 $('coinbasehero').className='hero-value '+(ok?'green':'red');
 $('coinbasebadge').textContent=ok?'CONNECTED':'OFFLINE';
 $('coinbasebadge').className='badge '+(ok?'ok':'');
 $('coinbasenote').textContent=ok?'Coinbase Advanced API is verbonden. Saldi worden read-only weergegeven.':'Coinbase authenticatie niet beschikbaar: '+(d.error_category||'onbekend');
}
function renderCoinbaseBalances(d){
 $('coinbaseaccounts').textContent=(d.active_account_count??d.account_count??'—')+' actief';
 $('coinbaseassetcount').textContent=d.asset_count??0;
 let rows=d.assets||[];
 $('coinbaseassets').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.currency)}</b></td><td>${num(x.available)}</td><td>${num(x.hold)}</td><td>${num(x.total)}</td></tr>`).join(''):'<tr><td colspan="4" class="sub">Geen niet-nul saldi gevonden</td></tr>';
}
function renderArbitrage(d){
 $('arbmode').textContent=d.mode==='shadow'?'shadow actief':(d.mode||'—'); $('arbhero').textContent=d.mode==='shadow'?'SCANNING':'OFFLINE'; $('arbhero').className='hero-value '+(d.mode==='shadow'?'green':'amber'); $('arbbadge').textContent=d.mode==='shadow'?'SCANNING':'OFFLINE'; $('arbbadge').className='badge '+(d.mode==='shadow'?'ok':''); let aas=$('arbAgentState'); if(aas){aas.textContent=d.mode==='shadow'?'shadow actief':'shadow offline';aas.className=d.mode==='shadow'?'green':'amber';}
 $('arbmode').className=d.mode==='shadow'?'green':'amber';
 $('arbchecked').textContent=new Date().toLocaleTimeString();
 let rows=d.markets||[];
 $('arbrows').innerHTML=rows.length?rows.map(x=>{
  let b=x.best_direction||{}, ok=x.status==='ok', act=!!b.actionable;
  return `<tr><td>${esc(x.market||'—')}</td><td>${esc(b.buy_venue||'—')}</td><td>${esc(b.sell_venue||'—')}</td><td>${b.gross_edge_pct==null?'—':Number(b.gross_edge_pct).toFixed(3)+'%'}</td><td class="${Number(b.net_edge_pct||0)>=0?'green':'amber'}">${b.net_edge_pct==null?'—':Number(b.net_edge_pct).toFixed(3)+'%'}</td><td class="${act?'green':'amber'}">${ok?(act?'kans':'geen kans'):'niet beschikbaar'}</td></tr>`;
 }).join(''):'<tr><td colspan="6" class="sub">Geen arbitragemarkten</td></tr>';
 $('arbnote').textContent='Shadow scanner · budget €'+Number(d.budget_eur||0).toFixed(2)+' · min. netto edge '+Number(d.min_net_edge_pct||0).toFixed(2)+'% · live orders verzonden: '+(d.live_orders_sent?'JA':'nee');
}
function renderFuturesAI(d){
 let rows=d.markets||[];
 $('futuresaibadge').textContent=d.runtime_error?'FEED ERROR':(d.fallback_used?'FALLBACK DATA':'AI SHADOW ACTIVE');
 $('futuresaibadge').className='badge '+(d.runtime_error?'':'ok');
 $('futuresairows').innerHTML=rows.length?rows.map(x=>{
  const review=x.review_status||'KEEP';
  const reviewClass=review==='PROMOTE_REVIEW'?'green':(review==='DROP'?'red':'amber');
  const side=x.position_side||'flat';
  const sideClass=side==='flat'?'sub':'blue';
  return `<tr><td><b>${esc(x.symbol||x.coin||'—')}</b></td><td>$ ${Number(x.mark_price||0).toLocaleString(undefined,{maximumFractionDigits:4})}</td><td>${Number(x.funding_bps||0).toFixed(3)} bps</td><td>${(Number(x.probability_up||0)*100).toFixed(1)}%</td><td>${(Number(x.confidence||0)*100).toFixed(1)}%</td><td><b>${esc(x.signal||'HOLD')}</b></td><td class="${sideClass}">${esc(side.toUpperCase())}</td><td>${esc(x.completed_trades||0)} (${esc(x.wins||0)}/${esc(x.losses||0)})</td><td class="${Number(x.realized_net_pnl_usd||0)>=0?'green':'red'}">$ ${Number(x.realized_net_pnl_usd||0).toFixed(2)}</td><td>${Number(x.max_drawdown_pct||0).toFixed(2)}%</td><td class="${reviewClass}"><b>${esc(review)}</b></td></tr>`;
 }).join(''):'<tr><td colspan="11" class="sub">Nog geen futures-data</td></tr>';
 const r=d.promotion_rules||{};
 $('futuresainote').textContent='Bron '+esc(d.active_source||'wachten')+(d.fallback_used?' (fallback)':'')+' · model '+esc(d.model||'—')+' · promotie-review pas na '+(r.min_completed_trades||0)+' trades, '+Number(r.min_winrate_pct||0).toFixed(0)+'% winrate, positieve PnL, DD ≤ '+Number(r.max_drawdown_pct||0).toFixed(1)+'% en modelaccuracy ≥ '+Number(r.min_model_accuracy_pct||0).toFixed(0)+'% · live orders: '+(d.live_orders_sent?'JA':'nee');
}
function renderShadow(d){
 let rows=d.strategies||[];
 $('shadowbadge').textContent=d.live_orders_sent?'ERROR':'SHADOW ACTIVE';
 $('shadowbadge').className='badge '+(d.live_orders_sent?'':'ok');
 $('shadowrows').innerHTML=rows.length?rows.map(x=>{
  const status=x.review_status||'KEEP';
  const statusClass=status==='PROMOTE'?'green':(status==='DROP'?'red':'amber');
  const position=x.position_open
    ? ('OPEN '+Number(x.position_qty||0).toLocaleString(undefined,{maximumSignificantDigits:6})+' @ '+money(x.entry_price||0))
    : 'FLAT';
  return `<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.symbol||'—')}</td><td>${esc(x.completed_trades||0)}</td><td>${esc(x.wins||0)}/${esc(x.losses||0)}</td><td>${Number(x.winrate_pct||0).toFixed(1)}%</td><td class="${Number(x.realized_net_pnl_eur||0)>=0?'green':'red'}">${money(x.realized_net_pnl_eur||0)}</td><td>${Number(x.max_drawdown_pct||0).toFixed(1)}%</td><td class="${x.position_open?'blue':'sub'}">${position}</td><td><b>${Number(x.score||0).toFixed(1)}</b></td><td class="${statusClass}"><b>${esc(status)}</b></td><td>${esc(x.last_signal||'—')}</td></tr>`;
 }).join(''):'<tr><td colspan="11" class="sub">Geen shadow strategieën</td></tr>';
 let r=d.promotion_rules||{};
 $('shadownote').textContent='PROMOTE = alle promotiegates gehaald · KEEP = meer data nodig / nog geen harde afkeur · DROP = na minimaal '+(r.min_completed_trades||0)+' trades negatieve PnL, duidelijke winrate-misser of te hoge drawdown. Promotie vereist '+Number(r.min_winrate_pct||0).toFixed(0)+'% winrate, ≥ '+money(r.min_net_pnl_eur||0)+' netto PnL en max '+Number(r.max_drawdown_pct||0).toFixed(1)+'% drawdown · live orders: '+(d.live_orders_sent?'JA':'nee');
}
function renderAllocator(d){
 let rows=d.recommendations||[];
 $('allocatorbadge').textContent=(d.mode||'advisory').toUpperCase();
 $('allocatorrows').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(x.strategy)}</td><td>${esc(x.mode)}</td><td>${esc(x.samples)}</td><td>${Number(x.score||0).toFixed(3)}</td><td>${money(x.base_allocation_eur)}</td><td><b>${money(x.recommended_allocation_eur)}</b></td></tr>`).join(''):'<tr><td colspan="6" class="sub">Geen allocatie-advies</td></tr>';
 $('allocatornote').textContent='Advisory only · totaalbudget €'+Number(d.global_budget_eur||0).toFixed(2)+' · max verschuiving '+Number(d.max_shift_pct||0).toFixed(0)+'% · live allocaties gewijzigd: '+(d.live_allocations_changed?'JA':'nee');
}
function renderGoal(d){
 const p=Math.max(0,Math.min(100,Number(d.progress_pct||0)));
 $('goalcurrent').textContent=money(d.current_equity_estimate_eur);
 $('goaltarget').textContent=money(d.target_equity_eur);
 $('goalprogress').textContent=p.toFixed(3)+'%';
 $('goalnext').textContent=d.next_milestone_eur==null?'DOEL BEREIKT':money(d.next_milestone_eur);
 $('goalbar').style.width=p+'%';
 $('goalbadge').textContent=d.target_reached?'TARGET REACHED':'€25K TARGET';
 $('goalbadge').className='badge '+(d.target_reached?'ok':'');
 $('goalnote').textContent='Gezamenlijk doel · resterend '+money(d.remaining_eur)+' · doel stuurt risico niet aan · martingale: uit';
}
function renderBinanceReference(d){
 $('binanceprice').textContent=d.price==null?'—':'$ '+Number(d.price).toLocaleString(undefined,{maximumFractionDigits:2});
 $('binanceinterval').textContent=Number(d.interval_seconds||1).toFixed(0)+' sec';
 $('binanceupdated').textContent=d.updated_at?new Date(Number(d.updated_at)*1000).toLocaleTimeString():'—';
 $('binancebadge').textContent=d.error?'FEED ERROR':'READ ONLY';
 $('binancebadge').className='badge '+(d.error?'':'ok');
 $('binancenote').textContent='Bron: '+esc(d.source||'binance_public')+' · live orders verzonden: '+(d.live_orders_sent?'JA':'nee')+(d.error?' · '+d.error:'');
}
function renderExecutionV2(d){
 let rows=d.orders||[];
 $('execv2badge').textContent=(d.mode||'advisory').toUpperCase();
 $('execv2badge').className='badge '+(d.apply_live?'live':'');
 $('execv2rows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="mono">${Number(x.age_seconds||0).toFixed(0)}s</td><td class="mono">${money(x.current_limit_price)}</td><td class="mono">${money(x.maker_target_price)}</td><td class="mono">${Number(x.move_bps||0).toFixed(1)} bps</td><td class="${x.recommend_reprice?'green':'amber'}">${x.recommend_reprice?'HERPRIJZEN':'wachten'} · ${esc(x.reason||'')}</td></tr>`).join(''):'<tr><td colspan="7" class="sub">Geen actieve orders om te beoordelen</td></tr>';
 $('execv2note').textContent='Maker-first advies · live wijzigen: '+(d.apply_live?'AAN':'uit')+' · orders gewijzigd: '+(d.live_orders_changed?'JA':'nee');
}
function renderOpportunities(d){
 let ranks=d.rankings||{}, keys=['market_maker','grid','sniper','mean_reversion','volatility_breakout'];
 let names={market_maker:'MarketMaker',grid:'GridRunner',sniper:'SniperBot',mean_reversion:'Mean Reversion',volatility_breakout:'Volatility Breakout'};
 let rows=keys.map(k=>({key:k,best:(ranks[k]||[]).find(x=>x.eligible)||(ranks[k]||[])[0]})).filter(x=>x.best);
 const scanned=Number(d.markets_scanned||0),configured=Number(d.markets_configured||0),maxm=Number(d.max_markets||60),errCount=Object.keys(d.errors||{}).length+(d.runtime_error?1:0);
 $('routerbadge').textContent=d.live_orders_sent?'ERROR':(scanned>=50?'50+ SCANNING':'SCANNING');
 $('routerbadge').className='badge '+(d.live_orders_sent?'':'ok');
 $('routerconfigured').textContent=configured||'—';$('routerscanned').textContent=scanned||'—';$('routertarget').textContent=maxm;$('routererrors').textContent=errCount;
 $('routererrors').className='v '+(errCount?'red':'green');
 $('routerrows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(names[x.key]||x.key)}</b></td><td>${esc(x.best.market)}</td><td class="mono">${Number(x.best.score||0).toFixed(1)}</td><td class="mono">${Number(x.best.spread_bps||0).toFixed(1)} bps</td><td class="mono">${Number(x.best.momentum_pct||0).toFixed(3)}%</td><td class="mono">${money(x.best.liquidity_eur)}</td></tr>`).join(''):'<tr><td colspan="6" class="sub">Nog onvoldoende router-data</td></tr>';
 $('routernote').textContent=scanned+' van '+configured+' beschikbare EUR-markten gescand · cap '+maxm+' · auto-discovery '+(d.auto_discover_eur?'AAN':'uit')+' · live orders verzonden: '+(d.live_orders_sent?'JA':'nee')+(d.runtime_error?' · fout: '+d.runtime_error:'');
}
function renderFeeEfficiency(d){
 let rows=d.rows||[];
 $('feerows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="${Number(x.realized_net_pnl_eur||0)>=0?'green':'red'}">${money(x.realized_net_pnl_eur)}</td><td>${money(x.fees_eur)}</td><td class="${x.fee_drag_pct!=null&&Number(x.fee_drag_pct)>50?'amber':''}">${x.fee_drag_pct==null?'—':Number(x.fee_drag_pct).toFixed(1)+'%'}</td><td>${money(x.net_per_exit_eur)}</td><td>${esc(x.state||'—')}</td></tr>`).join(''):'<tr><td colspan="7" class="sub">Nog onvoldoende fill-data</td></tr>';
 $('feenote').textContent='Fee-efficiency is meetdata · live wijzigingen: '+(d.live_changes?'JA':'nee');
}
function renderAutonomy(d){
 let p=d.plan||{},rows=p.rows||[],armed=!!d.armed;
 $('autonomymode').textContent=armed?(p.apply_live?'AUTONOMOUS LIVE':'ARMED / SHADOW PLAN'):'WACHT OP LIVE ARM';
 $('autonomymode').className='badge '+(armed&&p.apply_live?'live':'');
 $('autonomybadge').textContent='SET → EXECUTE → LEARN → REPEAT';
 $('autonomyrows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.current_market)}</td><td class="${x.desired_market!==x.current_market?'blue':''}">${esc(x.desired_market)}</td><td class="mini">${esc((x.allowed_markets||[]).join(', '))}</td><td class="mono">${Number(x.market_score||0).toFixed(1)}</td><td class="mono">${(Number(x.confidence||0)*100).toFixed(1)}%</td><td class="mono">${money(x.recommended_order_eur)}</td><td class="${x.may_switch?'green':'amber'}">${x.may_switch?'JA':'nee'}</td><td>${esc(x.reason||'—')}</td></tr>`).join(''):'<tr><td colspan="9" class="sub">Nog geen autonomy-plan beschikbaar</td></tr>';
 let rules=p.hard_rules||{};
 $('autonomynote').textContent='Operator-arm vereist: '+(d.operator_activation_required?'ja':'nee')+' · zelf armen: '+(rules.can_arm_itself?'JA':'nee')+' · budget verhogen: '+(rules.can_raise_global_budget?'JA':'nee')+' · leverage: '+(rules.can_use_leverage?'JA':'nee')+' · martingale: '+(rules.can_use_martingale?'JA':'nee');
}
function renderRiskLab(d){
 $('risklabbadge').textContent=d.live_orders_sent?'ERROR':'PAPER ONLY';
 $('risklabbadge').className='badge '+(d.live_orders_sent?'':'ok');
 $('risklableverage').textContent=Number(d.leverage||0).toFixed(1)+'×';
 $('risklabstake').textContent=money(d.current_stake_eur);
 $('risklabpnl').textContent=money(d.realized_net_pnl_eur);$('risklabpnl').className='v '+(Number(d.realized_net_pnl_eur||0)>=0?'green':'red');
 $('risklabdd').textContent=Number(d.max_drawdown_pct||0).toFixed(2)+'%';
 $('risklabnote').textContent='Trades '+(d.completed_trades||0)+' · winrate '+Number(d.winrate_pct||0).toFixed(1)+'% · martingale-stap max '+(d.max_martingale_steps||0)+' · live_capable: '+(d.live_capable?'JA':'nee');
}
function renderRisk(d){let pos=d.open_positions||d.positions||[];if(!Array.isArray(pos))pos=[];$('positions').innerHTML=pos.length?pos.map(x=>`<tr><td>${esc(x.symbol||x.market)}</td><td>${esc(x.side)}</td><td>${money(x.notional_eur??x.notional)}</td><td>${money(x.pnl_eur??x.pnl)}</td></tr>`).join(''):'<tr><td colspan="4" class="sub">Geen open posities</td></tr>'}
function renderProfit(d){
 let t=d.totals||{},rows=d.strategies||[],econ=Number(t.economic_pnl_eur||0),real=Number(t.realized_net_pnl_eur||0),unreal=Number(t.unrealized_net_pnl_eur||0);
 $('profitEconomic').textContent=money(econ);$('profitEconomic').className='value '+(econ>=0?'green':'red');
 $('profitRealized').textContent=money(real);$('profitRealized').className='value '+(real>=0?'green':'red');
 $('profitUnrealized').textContent=money(unreal);$('profitUnrealized').className='value '+(unreal>=0?'green':'red');
 $('profitEdge').textContent=Number(d.policy?.required_entry_edge_pct||0).toFixed(2)+'%';
 $('profitrows').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(x.strategy)}</td><td>${esc(x.market)}</td><td class="${Number(x.economic_pnl_eur||0)>=0?'green':'amber'}">${esc(x.state)}</td><td>${num(x.quantity)}</td><td>${money(x.break_even_exit_price)}</td><td>${money(x.min_profit_exit_price)}</td><td>${money(x.economic_pnl_eur)}</td></tr>`).join(''):'<tr><td colspan="7" class="sub">Geen profitdata</td></tr>';
}
function renderLiveState(d){
 let b=d.balances||{},eur=b.EUR||{},btc=b.BTC||{};
 $('eurlabel').textContent='Bitvavo EUR saldo (bot)';
 $('btclabel').textContent='Bitvavo BTC saldo (bot)';
 $('eur').textContent=money(eur.total||0);
 $('eurdelta').textContent='Beschikbaar '+money(eur.available||0)+' · in orders '+money(eur.in_order||0);
 $('btc').textContent=num(btc.total||0)+' BTC';
 $('btcrate').textContent=d.ticker_eur?'BTC/EUR '+Number(d.ticker_eur).toFixed(2):'BTC-koers niet beschikbaar';
 let rows=d.open_orders||[],count=Number(d.open_order_count||0);
 $('liveorders').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.market)}</b></td><td class="${x.side==='buy'?'side-buy':'side-sell'}">${esc((x.side||'').toUpperCase())}</td><td class="mono">${num(x.remaining_amount??x.amount)}</td><td class="mono">${money(x.price)}</td><td class="mono">${money(x.notional_eur)}</td><td><span class="status-chip open">${esc(x.status||'open')}</span></td></tr>`).join(''):'<tr><td colspan="6" class="sub">Geen open Bitvavo orders</td></tr>';
 $('liveordersnote').textContent=count+' open order(s) · rechtstreeks uit Bitvavo';
 $('openOrderBadge').textContent=count+' open';
 $('orderOpenCount').textContent=count;
}
function renderOrderActivity(d){
 let rows=d.orders||[],counts=d.status_counts||{};
 const filled=Number(counts.filled||0), canceled=Number(counts.canceled||0)+Number(counts.cancelled||0), errors=Number(counts.rejected||0)+Number(counts.error||0)+Number(counts.blocked||0);
 $('orderFilledCount').textContent=filled;$('orderCanceledCount').textContent=canceled;$('orderErrorCount').textContent=errors;
 $('activityBadge').textContent=(d.total_returned||0)+' recent';
 const when=ts=>ts?new Date(Number(ts)*1000).toLocaleString():'—';
 const chip=s=>{s=String(s||'unknown').toLowerCase();let k=['filled'].includes(s)?'filled':['canceled','cancelled','expired'].includes(s)?'canceled':['rejected','error','blocked'].includes(s)?'error':'open';return '<span class="status-chip '+k+'">'+esc(s)+'</span>'};
 $('orderactivity').innerHTML=rows.length?rows.map(x=>`<tr><td class="mono">${esc(when(x.created_at))}</td><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="${x.side==='buy'?'side-buy':'side-sell'}">${esc((x.side||'').toUpperCase())}</td><td>${esc(x.order_type||'—')}</td><td class="mono">${num(x.amount)}</td><td class="mono">${x.price?money(x.price):'MARKET'}</td><td class="mono">${esc(x.fill_count||0)} · ${num(x.filled_amount||0)}</td><td>${chip(x.status)}</td></tr>`).join(''):'<tr><td colspan="9" class="sub">Nog geen orders in het journal</td></tr>';
 $('orderactivitynote').textContent=(d.total_returned||0)+' orders getoond · nieuwste eerst · automatisch ververst';
}
function renderBitvavo(d,e){let ok=d.authenticated_probe===true;$('fusioncred').textContent=d.credentials_present?'aanwezig':'ontbreekt';$('fusioncred').className=d.credentials_present?'green':'red';$('fusionauth').textContent=ok?'geslaagd':'mislukt';$('fusionauth').className=ok?'green':'red';$('fusionendpoint').textContent='account + EUR balance';$('fusionmode').textContent=(e?.mode||'paper')+' · live '+(e?.live_execution_capability||'uit');$('fusionchecked').textContent=new Date().toLocaleTimeString();$('fusionnote').textContent=ok?(d.passed?'Bitvavo securitycontrole geslaagd.':'Bitvavo authenticatie geslaagd; aanvullende safety-checks zijn nog niet compleet.'):'Bitvavo read-only authenticatie niet geslaagd: '+((d.errors||[]).join(', ')||'onbekend');$('safetymode').textContent=e?.mode||'paper';$('fusionlive').textContent=e?.live_execution_capability||'uit';$('emergencystop').textContent=e?.emergency_stop?'ACTIEF':'niet actief'}
function setSectionError(label,error){$('apierror').textContent=label+': '+(error?.message||'niet beschikbaar')}
async function refreshLiveReadiness(){
 try{
  let d=await get('/api/live/readiness');
  const resume=!!d.resume_mode;
  $('liveready').textContent=d.ready?(resume?'READY TO RESUME':'READY'):'NOT READY';
  $('liveready').className=d.ready?'green':'amber';
  $('livecheck').textContent=d.ready
    ? (resume
      ? 'Bestaande Bitvavo-orders zijn aantoonbaar bot-owned en met het duurzame journal gereconcileerd. Hervatten blijft een expliciete operatoractie.'
      : 'Alle server-side voorwaarden zijn aanwezig. Activeren blijft een expliciete operatoractie.')
    : 'Nog niet klaar: '+Object.entries(d.gates).filter(([_,v])=>!v).map(([k])=>k).join(', ');
  const armed=!!d.armed; $('livebtn').disabled=!d.ready||armed; $('liveaction').disabled=!d.ready||armed; $('livestop').style.display=armed?'inline-block':'none'; if(armed){$('liveready').textContent='ARMED';$('liveready').className='red';$('livecheck').textContent='Live execution is actief voor dit proces. Stoppen zet nieuwe orders direct uit.';}
 }catch(e){$('liveready').textContent='ONBEKEND';$('livecheck').textContent=e.message;$('livebtn').disabled=true;$('liveaction').disabled=true}
}
async function strategyControl(name,action){
 try{
  const ctl=prompt('Vul je AUTOTRADER_CONTROL_TOKEN in. Deze wordt niet opgeslagen.');
  if(!ctl) return;
  const r=await fetch('/api/strategies/'+action,{method:'POST',headers:{...headers(),'Content-Type':'application/json','X-Autotrader-Token':ctl},body:JSON.stringify({name})});
  const data=await r.json(); if(!r.ok) throw Error(data.detail||'Strategieactie geweigerd');
  await refresh(); return data;
 }catch(e){alert(e.message||'Strategieactie mislukt')}
}
async function startMarketMaker(){await strategyControl('market_maker','start')}
async function stopMarketMaker(){await strategyControl('market_maker','stop')}
async function groupStrategyControl(action){
 try{
  const ctl=prompt('Vul je AUTOTRADER_CONTROL_TOKEN in. Deze wordt niet opgeslagen.');
  if(!ctl) return;
  const r=await fetch('/api/strategies/'+action,{method:'POST',headers:{...headers(),'X-Autotrader-Token':ctl}});
  const data=await r.json(); if(!r.ok) throw Error(data.detail||'Groepsactie geweigerd');
  await refresh(); return data;
 }catch(e){alert(e.message||'Groepsactie mislukt')}
}
async function activateLive(){
 try{
  const phrase=prompt('Bevestig live orders door exact I_UNDERSTAND_LIVE_ORDERS in te vullen.');
  if(phrase!=='I_UNDERSTAND_LIVE_ORDERS') return;
  const r=await fetch('/api/live/activate',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({confirmation:phrase})});
  const d=await r.json(); if(!r.ok) throw Error(d.detail?.message||d.detail||'Activering geweigerd');
  await refreshLiveReadiness(); alert('Live Trading is geactiveerd. De bot kan nu nieuwe orders uitvoeren.');
 }catch(e){alert(e.message||'Live activering mislukt');}
}
async function deactivateLive(){
 try{
  const r=await fetch('/api/live/deactivate',{method:'POST',headers:headers()});
  const d=await r.json(); if(!r.ok) throw Error(d.detail||'Stoppen mislukt');
  await refreshLiveReadiness(); alert('Live Trading is gestopt. Nieuwe orders worden niet meer uitgevoerd.');
 }catch(e){alert(e.message||'Stoppen mislukt');}
}
async function refresh(){let now=new Date().toLocaleString();$('last').textContent='Bijwerken…';$('apierror').textContent='';let entries=await Promise.allSettled([get('/api/paper/report'),get('/api/execution/status'),get('/api/pnl/summary'),get('/api/health'),get('/api/security/bitvavo'),get('/api/risk/status'),get('/api/markets/overview'),get('/api/strategies'),get('/api/bitvavo/live-state'),get('/api/pnl/live'),get('/api/security/coinbase'),get('/api/coinbase/live-state'),get('/api/arbitrage/coinbase-bitvavo'),get('/api/shadow/strategies'),get('/api/allocator/v2'),get('/api/orders/activity?limit=100'),get('/api/optimization/execution-v2'),get('/api/optimization/opportunities'),get('/api/optimization/fee-efficiency'),get('/api/goals/portfolio'),get('/api/reference/binance-btc'),get('/api/autonomy/status'),get('/api/risk-lab/leverage-martingale'),get('/api/research/futures-ai')]);let [r,e,s,h,f,k,m,a,v,p,cb,cbb,arb,sh,al,oa,ev2,op,fe,goal,bref,auto,rl,fai]=entries;let fail=(entry,label)=>{if(entry.status==='rejected')setSectionError(label,entry.reason)};if(r.status==='fulfilled')renderReport(r.value);else fail(r,'Portfolio');if(e.status==='fulfilled')renderExec(e.value);else fail(e,'Execution');if(s.status==='fulfilled')renderStrategies(s.value);else fail(s,'PnL');if(h.status==='fulfilled'){$('ticker').textContent=h.value.runtime?.ticker_running?'actief':'gestopt';$('updated').textContent=new Date().toLocaleTimeString();$('healthbar').style.width=h.value.runtime?.last_tick_error?'25%':'100%'}else fail(h,'Runtime');if(f.status==='fulfilled')renderBitvavo(f.value,e.status==='fulfilled'?e.value:{});else fail(f,'Bitvavo');if(k.status==='fulfilled')renderRisk(k.value);else fail(k,'Risk');if(m.status==='fulfilled')renderMarkets(m.value);else fail(m,'Markten');if(a.status==='fulfilled')renderAgents(a.value);else fail(a,'Agents');if(v.status==='fulfilled')renderLiveState(v.value);else fail(v,'Open orders');if(p.status==='fulfilled')renderProfit(p.value);else fail(p,'Profit supervisor');if(cb.status==='fulfilled')renderCoinbase(cb.value);else fail(cb,'Coinbase');if(cbb.status==='fulfilled')renderCoinbaseBalances(cbb.value);else fail(cbb,'Coinbase saldo');if(arb.status==='fulfilled')renderArbitrage(arb.value);else fail(arb,'Arbitrage');if(sh.status==='fulfilled')renderShadow(sh.value);else fail(sh,'Shadow bots');if(al.status==='fulfilled')renderAllocator(al.value);else fail(al,'Allocator v2');if(oa.status==='fulfilled')renderOrderActivity(oa.value);else fail(oa,'Orderhistorie');if(ev2.status==='fulfilled')renderExecutionV2(ev2.value);else fail(ev2,'Execution v2');if(op.status==='fulfilled')renderOpportunities(op.value);else fail(op,'Opportunity Router');if(fe.status==='fulfilled')renderFeeEfficiency(fe.value);else fail(fe,'Fee Efficiency');if(goal.status==='fulfilled')renderGoal(goal.value);else fail(goal,'€25k doel');if(bref.status==='fulfilled')renderBinanceReference(bref.value);else fail(bref,'Binance reference');if(auto.status==='fulfilled')renderAutonomy(auto.value);else fail(auto,'Autonomy');if(rl.status==='fulfilled')renderRiskLab(rl.value);else fail(rl,'Risk Lab');if(fai.status==='fulfilled')renderFuturesAI(fai.value);else fail(fai,'Futures AI');refreshLiveReadiness();$('last').textContent='Bijgewerkt '+now}
function connect(){try{let scheme=location.protocol==='https:'?'wss':'ws';let credential=apiKey||token;if(!credential){$('socket').textContent='auth vereist';return}socket=new WebSocket(`${scheme}://${location.host}/ws/paper`,['at-v1',credential]);socket.onopen=()=>{$('socket').textContent='verbonden';$('socket').className='green'};socket.onmessage=e=>{try{if(($('mode').textContent||'').toLowerCase()!=='live')renderReport(JSON.parse(e.data))}catch(_){}};socket.onclose=()=>{$('socket').textContent='herstellen…';setTimeout(connect,4000)}}catch(_){$('socket').textContent='niet beschikbaar'}}
if(token||apiKey){$('login').classList.add('hidden');$('app').classList.remove('hidden');refresh();connect()}
setInterval(()=>{if(!$('app').classList.contains('hidden'))refresh()},5000);
</script></body></html>'''


def dashboard_html() -> str:
    return DASHBOARD_HTML
