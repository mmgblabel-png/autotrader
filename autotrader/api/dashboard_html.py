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
<div class="section-title"><h3>Hedge Fund Command Center</h3><div class="line"></div><span id="fundbadge" class="badge">FUND CORE</span></div>
<section class="section">
  <div class="card control-card">
    <div class="control-head">
      <div><div class="eyebrow">Capital preservation mandate</div><div class="control-title">Fund Core · €25.000 Protected Capital</div><div id="fundnote" class="control-sub">Fund NAV, high-water mark, risk capital en ledger-integriteit.</div></div>
      <span id="fundmode" class="badge ok">GROEI</span>
    </div>
    <div class="order-kpis">
      <div class="order-kpi"><div class="k">Fund NAV</div><div id="fundnav" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Doel</div><div id="fundtarget" class="v blue">€50.000,00</div></div>
      <div class="order-kpi"><div class="k">Drawdown</div><div id="funddrawdown" class="v amber">—</div></div>
      <div class="order-kpi"><div class="k">Risk capital beschikbaar</div><div id="fundriskcapital" class="v">—</div></div>
    </div>
    <div class="bar"><i id="fundprogressbar" style="width:0%"></i></div>
    <div class="metric" style="margin-top:12px"><span>Target progress</span><b id="fundprogress">—</b></div>
    <div class="metric"><span>Protected floor</span><b id="fundfloor">—</b></div>
    <div class="metric"><span>Protected zone incl. buffer</span><b id="fundzone">—</b></div>
    <div class="metric"><span>Gross exposure</span><b id="fundgross">—</b></div>
    <div class="metric"><span>Required deleveraging</span><b id="funddelever">—</b></div>
    <div class="metric"><span>NAV verificatie</span><b id="fundnavverified">—</b></div>
    <div class="metric"><span>Growth stage</span><b id="fundstage">—</b></div>
    <div class="metric"><span>Volgende milestone</span><b id="fundnext">—</b></div>
    <div class="metric"><span>Track record</span><b id="fundtrack">—</b></div>
    <div class="metric"><span>Operating roles</span><b id="fundroles">—</b></div>
    <div class="metric"><span>Ledger integrity</span><b id="fundledger">—</b></div>
  </div>
</section>
<section class="section">
  <div class="card control-card">
    <div class="control-head">
      <div><div class="eyebrow">Institutional operating model</div><div class="control-title">AI Hedge Fund Prototype</div><div id="prototypeNote" class="control-sub">Research, accounting, compliance en investor-readiness vanuit dezelfde Fund Ledger.</div></div>
      <span id="prototypeBadge" class="badge">BUILDING</span>
    </div>
    <div class="order-kpis">
      <div class="order-kpi"><div class="k">Research Agents</div><div id="prototypeAgents" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Research Coverage</div><div id="prototypeCoverage" class="v blue">—</div></div>
      <div class="order-kpi"><div class="k">Recorded Fills</div><div id="prototypeFills" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Recorded Net PnL</div><div id="prototypePnl" class="v">—</div></div>
    </div>
    <div class="metric" style="margin-top:12px"><span>24h / 7d / 30d realized</span><b id="prototypeWindows">—</b></div>
    <div class="metric"><span>Profit factor</span><b id="prototypePf">—</b></div>
    <div class="metric"><span>Compliance controls</span><b id="prototypeCompliance">—</b></div>
    <div class="metric"><span>Investor reporting</span><b id="prototypeInvestor">—</b></div>
    <div class="metric"><span>Autonomous policy</span><b id="fundAutoPolicy">—</b></div>
    <div class="metric"><span>Market regime</span><b id="fundAutoRegime">—</b></div>
    <div class="metric"><span>Research / Monte Carlo</span><b id="fundAutoResearch">—</b></div>
    <div class="metric"><span>Monte Carlo risk</span><b id="fundAutoMonte">—</b></div>
    <div style="margin-top:12px"><div class="mini">Recorded realized equity curve</div><canvas id="prototypeEquity" height="92" style="width:100%;height:92px"></canvas></div>
    <div class="table-wrap" style="margin-top:12px"><table class="table compact"><thead><tr><th>Agent</th><th>State</th><th>Signals</th><th>Confidence</th><th>Score</th></tr></thead><tbody id="prototypeAgentRows"><tr><td colspan="5" class="sub">Research department laden…</td></tr></tbody></table></div>
  </div>
</section>
<section class="section"><div class="card control-card"><div class="control-head"><div><div class="eyebrow">Execution monitor</div><div class="control-title">Order Control Center</div><div class="control-sub">Direct zicht op open Bitvavo-orders én iedere recente bot-order uit het duurzame journal.</div></div><span class="badge live">READ ONLY · AUTO REFRESH</span></div><div class="order-kpis"><div class="order-kpi"><div class="k">Nu open</div><div id="orderOpenCount" class="v blue">0</div></div><div class="order-kpi"><div class="k">Recent gevuld</div><div id="orderFilledCount" class="v green">0</div></div><div class="order-kpi"><div class="k">Geannuleerd</div><div id="orderCanceledCount" class="v">0</div></div><div class="order-kpi"><div class="k">Fouten laatste 3u</div><div id="orderErrorCount" class="v">0</div></div></div><div class="order-layout"><div><div class="exchange-head"><div><div class="exchange-name">Open orders</div><div class="mini">Rechtstreeks van Bitvavo</div></div><span id="openOrderBadge" class="badge">0 open</span></div><div class="table-wrap"><table class="table compact"><thead><tr><th>Markt</th><th>Side</th><th>Qty</th><th>Prijs</th><th>Waarde</th><th>Status</th></tr></thead><tbody id="liveorders"><tr><td colspan="6" class="sub">Laden…</td></tr></tbody></table></div><div id="liveordersnote" class="sub" style="margin-top:9px">Read-only uit Bitvavo.</div></div><div><div class="exchange-head"><div><div class="exchange-name">Alle recente orders</div><div class="mini">Nieuwste eerst · order-ID's en secrets bewust verborgen</div></div><span id="activityBadge" class="badge ok">journal</span></div><div class="table-wrap"><table class="table compact"><thead><tr><th>Tijd</th><th>Bot</th><th>Markt</th><th>Side</th><th>Type</th><th>Qty</th><th>Prijs</th><th>Fills</th><th>Status</th></tr></thead><tbody id="orderactivity"><tr><td colspan="9" class="sub">Orderhistorie laden…</td></tr></tbody></table></div><div id="orderactivitynote" class="sub" style="margin-top:9px">Duurzame journal-history.</div></div></div></div></section>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Rolling 3-uurs rapport</div><div class="mini">Alleen activiteit van de laatste 3 uur · huidige PnL/exposure · live router-signalen</div></div><span id="threehbadge" class="badge ok">3H LIVE</span></div>
    <div class="order-kpis" style="grid-template-columns:repeat(4,1fr);margin-top:8px">
      <div class="order-kpi"><div class="k">Orders 3u</div><div id="threehOrders" class="v blue">—</div></div>
      <div class="order-kpi"><div class="k">Fills 3u</div><div id="threehFills" class="v green">—</div></div>
      <div class="order-kpi"><div class="k">Fouten 3u</div><div id="threehErrors" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Fees 3u</div><div id="threehFees" class="v">—</div></div>
    </div>
    <div class="order-kpis" style="grid-template-columns:repeat(4,1fr);margin-top:8px">
      <div class="order-kpi"><div class="k">Actieve exposure</div><div id="threehExposure" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Vrije headroom</div><div id="threehHeadroom" class="v green">—</div></div>
      <div class="order-kpi"><div class="k">Economische PnL nu</div><div id="threehPnl" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Scanner</div><div id="threehScanner" class="v blue">—</div></div>
    </div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Agent</th><th>Beste markt</th><th>Score</th><th>Signal</th><th>Richting</th><th>Spread</th></tr></thead><tbody id="threehOpportunities"><tr><td colspan="6" class="sub">3-uurs rapport laden…</td></tr></tbody></table></div>
    <div id="threehnote" class="sub" style="margin-top:9px">Rolling window; historische fouten van vóór deze 3 uur tellen niet mee.</div>
  </div>
</section>
<section class="section two"><div class="card"><h2>Open posities</h2><table class="table"><thead><tr><th>Symbool</th><th>Side</th><th>Notional</th><th>PnL</th></tr></thead><tbody id="positions"><tr><td colspan="4" class="sub">Laden…</td></tr></tbody></table></div><div class="card"><h2>Execution & risk</h2><div class="metric"><span>Status</span><b id="execmode">—</b></div><div class="metric"><span>Actieve bot-exposure</span><b id="exposure">—</b></div><div class="metric"><span>Vrije exposure-headroom</span><b id="remainingexposure">—</b></div><div class="metric"><span>Entry-turnover vandaag</span><b id="entryturnover">—</b></div><div class="metric"><span>Dagverlies</span><b id="loss">—</b></div><div class="metric"><span>Max per order</span><b id="maxtrade">—</b></div><div class="metric"><span>Max bot-exposure</span><b id="maxdaily">—</b></div><div class="metric"><span>Max dagverlies</span><b id="maxloss">—</b></div></div></section>
<section class="section"><div class="card"><h2>Profit supervisor</h2><div class="grid" style="margin-bottom:12px"><div><div class="label">Economische PnL</div><div id="profitEconomic" class="value">—</div></div><div><div class="label">Gerealiseerd netto</div><div id="profitRealized" class="value">—</div></div><div><div class="label">Ongerealiseerd na exit-kosten</div><div id="profitUnrealized" class="value">—</div></div><div><div class="label">Min. edge nieuwe entry</div><div id="profitEdge" class="value">—</div></div></div><table class="table"><thead><tr><th>Bot</th><th>Markt</th><th>Status</th><th>Inventory</th><th>Break-even</th><th>Min winst-exit</th><th>Net PnL</th></tr></thead><tbody id="profitrows"><tr><td colspan="7" class="sub">Laden…</td></tr></tbody></table><div class="sub" style="margin-top:10px">Gebaseerd op echte journal-fills en geschatte toekomstige fee/slippage. Geen winstgarantie.</div></div></section>
<section class="section two"><div class="card"><h2>Strategieën</h2><table class="table"><thead><tr><th>Naam</th><th>Status</th><th>PnL</th><th>Trades</th></tr></thead><tbody id="strategies"><tr><td colspan="4" class="sub">Laden…</td></tr></tbody></table></div><div class="card"><h2>Runtime</h2><div class="metric"><span>Feed/ticker</span><b id="ticker">—</b></div><div class="metric"><span>Laatste update</span><b id="updated">—</b></div><div class="metric"><span>WebSocket</span><b id="socket">verbinden…</b></div><div class="bar"><i id="healthbar" style="width:0%"></i></div><div class="sub" style="margin-top:8px">Gezondheidsindicator op basis van ticker en laatste fout.</div></div></section>
<section class="section two"><div class="card"><h2>Live Market Universe</h2><table class="table"><thead><tr><th>Markt</th><th>Venue</th><th>Feed</th><th>Agents</th><th>Orders</th></tr></thead><tbody id="markets"><tr><td colspan="5" class="sub">Laden…</td></tr></tbody></table><div id="marketnote" class="sub" style="margin-top:10px">Volledige Bitvavo spot scanner; crypto→crypto research/shadow, live uitvoering alleen via gevalideerde EUR-routes en alle risk-gates.</div></div><div class="card"><h2>Trading agents</h2><div id="agents"><div class="sub">Laden…</div></div><div class="notice" style="margin-top:12px">Workflow: marktdata → strategie-signaal → risicocontrole → order-intentie → journal/PnL. Live execution blijft fail-closed tot alle gates én handmatige activatie gereed zijn.</div></div></section>
<div class="section-title"><h3>Profit Optimization v2</h3><div class="line"></div><span class="badge live">AUTONOMOUS AFTER ARM</span></div>
<section class="section exchange-grid">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Gezamenlijk botdoel</div><div class="mini">Alle bots dragen bij aan één portfolio-doel · nooit een reden om risico te verhogen</div></div><span id="goalbadge" class="badge">€25K TARGET</span></div>
    <div class="grid" style="margin-bottom:12px">
      <div><div class="label">Huidige equity-schatting</div><div id="goalcurrent" class="value">—</div></div>
      <div><div class="label">Doel</div><div id="goaltarget" class="value blue">€ 25.000</div></div>
      <div><div class="label">Per dag nodig</div><div id="goaldaily" class="value green">—</div></div>
      <div><div class="label">Dagelijkse groei nodig</div><div id="goalcompound" class="value">—</div></div>
    </div>
    <div class="grid" style="margin-bottom:12px">
      <div><div class="label">Voortgang</div><div id="goalprogress" class="value">—</div></div>
      <div><div class="label">Volgende mijlpaal</div><div id="goalnext" class="value amber">—</div></div>
      <div><div class="label">Horizon</div><div id="goaldays" class="value">—</div></div>
      <div><div class="label">Resterend</div><div id="goalremaining" class="value">—</div></div>
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
    <div class="exchange-head"><div><div class="exchange-name">Full Market Opportunity Router</div><div class="mini">Alle Bitvavo spotmarkten op spread, EUR-genormaliseerde liquiditeit, momentum en volatiliteit</div></div><span id="routerbadge" class="badge ok">SCANNING</span></div>
    <div class="order-kpis" style="grid-template-columns:repeat(4,1fr);margin-top:8px">
      <div class="order-kpi"><div class="k">Geconfigureerd</div><div id="routerconfigured" class="v blue">—</div></div>
      <div class="order-kpi"><div class="k">Nu gescand</div><div id="routerscanned" class="v green">—</div></div>
      <div class="order-kpi"><div class="k">Scanner cap</div><div id="routertarget" class="v">500</div></div>
      <div class="order-kpi"><div class="k">Fouten</div><div id="routererrors" class="v">0</div></div>
    </div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Strategie</th><th>Beste markt</th><th>Score</th><th>Signal</th><th>Richting</th><th>Spread</th><th>Momentum</th><th>Liquiditeit</th></tr></thead><tbody id="routerrows"><tr><td colspan="8" class="sub">Opportunity Router laden…</td></tr></tbody></table></div>
    <div id="routernote" class="sub" style="margin-top:9px">Read-only multi-market scan.</div>
  </div>
</section>
<div class="section-title"><h3>Full Exchange Universe</h3><div class="line"></div><span class="badge">BITVAVO + COINBASE</span></div>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">All Spot Markets</div><div class="mini">Fiat + stablecoin + crypto→crypto · read-only discovery · EUR bridge valuation</div></div><span id="universebadge" class="badge ok">READ ONLY</span></div>
    <div class="order-kpis" style="grid-template-columns:repeat(6,1fr);margin-top:8px">
      <div class="order-kpi"><div class="k">Bitvavo tradable</div><div id="unibv" class="v blue">—</div></div>
      <div class="order-kpi"><div class="k">Coinbase tradable</div><div id="unicb" class="v blue">—</div></div>
      <div class="order-kpi"><div class="k">Crypto→crypto</div><div id="unicrypto" class="v green">—</div></div>
      <div class="order-kpi"><div class="k">Exact overlap</div><div id="unioverlap" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Overlap crypto→crypto</div><div id="uniccoverlap" class="v">—</div></div>
      <div class="order-kpi"><div class="k">Status</div><div id="unierror" class="v green">OK</div></div>
    </div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Venue</th><th>Markt</th><th>Type</th><th>Quote</th><th>Score</th><th>Spread</th><th>Depth EUR</th><th>Live route</th></tr></thead><tbody id="universerows"><tr><td colspan="8" class="sub">Volledige markt-universe laden…</td></tr></tbody></table></div>
    <div id="universenote" class="sub" style="margin-top:9px">Crypto→crypto wordt volledig gescand. Live execution blijft alleen actief waar accounting/risk-gates gevalideerd zijn.</div>
  </div>
</section>
<section class="section exchange-grid">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Fee Efficiency</div><div class="mini">Netto PnL per bot na gemeten fees · fee-drag zichtbaar</div></div><span id="feebadge" class="badge">metrics</span></div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Bot</th><th>Markt</th><th>Netto PnL</th><th>Fees</th><th>Fee drag</th><th>Net / exit</th><th>Status</th></tr></thead><tbody id="feerows"><tr><td colspan="7" class="sub">Fee-efficiency laden…</td></tr></tbody></table></div>
    <div id="feenote" class="sub" style="margin-top:9px">Allocator v2 gebruikt deze metrics alleen als advies; live-budgetten worden niet automatisch gewijzigd.</div>
  </div>
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Fee & Margin Reality</div><div class="mini">Werkelijke Bitvavo account-fees · ordertype per live agent · read-only</div></div><span id="feerealitybadge" class="badge">READ ONLY</span></div>
    <div class="order-kpis" style="grid-template-columns:repeat(3,1fr);margin-top:8px">
      <div class="order-kpi"><div class="k">Maker</div><div id="actualmakerfee" class="v green">—</div></div>
      <div class="order-kpi"><div class="k">Taker</div><div id="actualtakerfee" class="v">—</div></div>
      <div class="order-kpi"><div class="k">30d volume</div><div id="feevolume" class="v blue">—</div></div>
    </div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Bot</th><th>Ordertype</th><th>Fee klasse</th><th>Fee/leg</th><th>2-leg fees</th><th>Kosten + slip</th><th>Research gross edge</th></tr></thead><tbody id="feerealityrows"><tr><td colspan="7" class="sub">Account-fees laden…</td></tr></tbody></table></div>
    <div id="feerealitynote" class="sub" style="margin-top:9px">Meetlaag alleen; live profit-gates worden niet automatisch aangepast.</div>
  </div>
</section>
<div class="section-title"><h3>Autonomous Control Loop</h3><div class="line"></div><span id="autonomybadge" class="badge">SET → EXECUTE → LEARN → REPEAT</span></div>
<section class="section">
  <div class="card">
    <div class="exchange-head"><div><div class="exchange-name">Autonomous Decision Engine</div><div class="mini">Na operator-arm kiest het systeem zelf markt + ordergrootte binnen harde caps</div></div><span id="autonomymode" class="badge">controleren</span></div>
    <div class="table-wrap"><table class="table compact"><thead><tr><th>Agent</th><th>Huidige markt</th><th>Gewenste markt</th><th>Live opties</th><th>Score</th><th>Signal</th><th>Confidence</th><th>Entry</th><th>Order €</th><th>Switch</th><th>Reden</th></tr></thead><tbody id="autonomyrows"><tr><td colspan="11" class="sub">Autonomy laden…</td></tr></tbody></table></div>
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
<div class="section-title"><h3>Shadow Fast Lane</h3><div class="line"></div><span class="badge">NO LIVE ORDERS</span></div>
<section class="section exchange-grid"><div class="card"><div class="exchange-head"><div><div class="exchange-name">Shadow Strategy Scorecard</div><div class="mini">Topmarkten parallel · candle-backfill + live marketdata · simulated fills · fees/slippage included</div></div><span id="shadowbadge" class="badge">shadow</span></div><div style="overflow-x:auto"><table class="table compact"><thead><tr><th>Bot</th><th>Markt</th><th>Trades</th><th>W/L</th><th>Winrate</th><th>Net PnL</th><th>DD</th><th>Positie</th><th>Score</th><th>Status</th><th>Signaal</th></tr></thead><tbody id="shadowrows"><tr><td colspan="11" class="sub">Shadow bots laden…</td></tr></tbody></table></div><div id="shadownote" class="sub" style="margin-top:10px">Deze bots mogen geen echte orders plaatsen.</div></div><div class="card"><div class="exchange-head"><div><div class="exchange-name">Strategy Allocator v2</div><div class="mini">Performance-weighted advies binnen hetzelfde totaalbudget</div></div><span id="allocatorbadge" class="badge">advisory</span></div><table class="table compact"><thead><tr><th>Strategie</th><th>Mode</th><th>Samples</th><th>Score</th><th>Basis</th><th>Advies</th></tr></thead><tbody id="allocatorrows"><tr><td colspan="6" class="sub">Allocator laden…</td></tr></tbody></table><div id="allocatornote" class="sub" style="margin-top:10px">Live allocaties worden niet automatisch gewijzigd.</div></div></section>
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
function renderExec(d){let l=d.limits||{};$('mode').textContent=d.mode||'paper';$('execmode').textContent=(d.mode||'paper')+' · '+(d.live_execution_capability||'onbekend');$('exposure').textContent=money(d.daily_exposure_eur||0);$('remainingexposure').textContent=money(d.remaining_daily_exposure_eur||0);$('entryturnover').textContent=money(d.daily_entry_turnover_eur||0);$('loss').textContent=money(d.daily_loss_eur||0);$('maxtrade').textContent=money(l.max_trade_eur);$('maxdaily').textContent=money(l.max_daily_exposure_eur);$('maxloss').textContent=money(l.max_daily_loss_eur);$('exposure').className=Number(d.daily_exposure_eur||0)>Number(l.max_daily_exposure_eur||0)?'red':'green';$('remainingexposure').className=Number(d.remaining_daily_exposure_eur||0)>=5?'green':'amber'}
function renderStrategies(d){let rows=d.pnl_per_strategy||[];$('strategies').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(x.name)}</td><td><span class="status"><i class="dot ${x.status==='running'?'':'off'}"></i>${esc(x.status)}</span></td><td>${money(x.pnlAllTime)}</td><td>${esc(x.tradesToday??0)}</td></tr>`).join(''):'<tr><td colspan="4" class="sub">Geen strategieën</td></tr>'}
function renderMarkets(d){let rows=(d.markets||[]).filter(x=>x.symbol&&x.symbol!=='*');$('markets').innerHTML=rows.length?rows.map(x=>{let live=x.price_status==='live';return `<tr><td><b>${esc(x.symbol)}</b></td><td>${esc(d.venue||'—')}</td><td><span class="status"><i class="dot ${live?'':'off'}"></i>${esc(x.price_status||'onbekend')}</span></td><td>${esc((x.strategies||[]).join(', ')||'scanner')}</td><td>${d.orders_enabled?'ingeschakeld':'uit'}</td></tr>`}).join(''):'<tr><td colspan="5" class="sub">Geen vaste markten geconfigureerd</td></tr>';$('marketnote').textContent=(d.router_scanned||0)+'/'+(d.router_configured||0)+' markten gescand · '+rows.length+' huidige agent-markten zichtbaar · wildcard loopt via de 60-market scanner.'}
function renderAgents(d){let names={market_maker:'Market maker · passieve spread',arbitrage:'Arbitrage hunter · prijsverschil',grid:'Grid runner · inventory grid',grid_eth:'Grid runner ETH · inventory grid',sniper:'Sniper bot · momentum'};let rows=d.strategies||[];$('agents').innerHTML=rows.length?rows.map(x=>{let arb=x.name==='arbitrage',label=x.running?'actief':(arb?'shadow gereed':'gestopt'),cls=x.running?'green':(arb?'blue':'amber'),id=arb?' id="arbAgentState"':'';return `<div class="metric"><span>${esc(names[x.name]||x.name)}<small class="sub"> · ${x.live_capable?'live':'shadow'} · €${Number(x.allocation_eur||0).toFixed(0)}</small></span><b${id} class="${cls}">${label}</b></div>`}).join(''):'<div class="sub">Geen agents geregistreerd</div>'}
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
 $('goaldaily').textContent=money(d.required_daily_linear_eur);
 $('goalcompound').textContent=Number(d.required_daily_compound_pct||0).toFixed(3)+'%';
 $('goaldays').textContent=Number(d.target_days||0).toFixed(0)+' dagen';
 $('goalremaining').textContent=money(d.remaining_eur);
 $('goalprogress').textContent=p.toFixed(3)+'%';
 $('goalnext').textContent=d.next_milestone_eur==null?'DOEL BEREIKT':money(d.next_milestone_eur);
 $('goalbar').style.width=p+'%';
 $('goalbadge').textContent=d.target_reached?'TARGET REACHED':'€50K GROWTH TARGET';
 $('goalbadge').className='badge '+(d.target_reached?'ok':'');
 $('goalnote').textContent='Dagstand = benodigde gemiddelde netto groei vanaf de huidige equity over '+Number(d.target_days||0).toFixed(0)+' dagen. Dit is een doelmeter, geen reden om slechtere trades te forceren.';
}
function renderBinanceReference(d){
 $('binanceprice').textContent=d.price==null?'—':'$ '+Number(d.price).toLocaleString(undefined,{maximumFractionDigits:2});
 $('binanceinterval').textContent=Number(d.interval_seconds||1).toFixed(0)+' sec';
 $('binanceupdated').textContent=d.updated_at?new Date(Number(d.updated_at)*1000).toLocaleTimeString():'—';
 $('binancebadge').textContent=d.error?'FEED ERROR':'READ ONLY';
 $('binancebadge').className='badge '+(d.error?'':'ok');
 $('binancenote').textContent='Bron: '+esc(d.source||'binance_public')+' · live orders verzonden: '+(d.live_orders_sent?'JA':'nee')+(d.error?' · '+d.error:'');
}
function renderThreeHour(d){
 let a=d.activity||{},p=d.pnl_now||{},ops=d.opportunities||[],errs=Number(a.error_orders||0);
 $('threehOrders').textContent=Number(a.orders_created||0);
 $('threehFills').textContent=Number(a.fills||0);
 $('threehErrors').textContent=errs;$('threehErrors').className='v '+(errs?'red':'green');
 $('orderErrorCount').textContent=errs;$('orderErrorCount').className='v '+(errs?'red':'green');
 $('threehFees').textContent=money(a.fees_eur||0);
 $('threehExposure').textContent=money(d.active_exposure_eur||0);
 $('threehHeadroom').textContent=money(d.remaining_exposure_eur||0);
 $('threehPnl').textContent=money(p.economic_pnl_eur||0);$('threehPnl').className='v '+(Number(p.economic_pnl_eur||0)>=0?'green':'red');
 $('threehScanner').textContent=Number(d.router_scanned||0)+'/60';
 $('threehbadge').textContent=d.armed?'3H · ARMED':'3H · DISARMED';$('threehbadge').className='badge '+(d.armed?'live':'ok');
 $('threehOpportunities').innerHTML=ops.length?ops.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="mono">${Number(x.score||0).toFixed(1)}</td><td class="mono">${Number(x.signal_strength||0).toFixed(1)}</td><td>${esc(x.signal_direction||'—')}</td><td class="mono">${Number(x.spread_bps||0).toFixed(1)} bps</td></tr>`).join(''):'<tr><td colspan="6" class="sub">Nog geen router-data in deze cyclus</td></tr>';
 let ev=d.execution_v2||{},ce=(ev.errors||[]).length,orders=Number(a.orders_created||0),fills=Number(a.fills||0),fillRate=orders>0?Math.min(100,(fills/orders)*100):0,feePerFill=fills>0?Number(a.fees_eur||0)/fills:0;
 $('threehnote').textContent='Rolling laatste 3 uur · fill/order '+fillRate.toFixed(1)+'% · fee per fill '+money(feePerFill)+' · open orders nu '+Number(a.open_orders_now||0)+' · entry-turnover vandaag '+money(d.daily_entry_turnover_eur||0)+' · Execution v2 cancel-fouten laatste cyclus '+ce+'.';
}
function renderExecutionV2(d){
 let rows=d.orders||[],actions=d.last_live_actions||{},errs=actions.errors||[];
 $('execv2badge').textContent=d.apply_live?'LIVE MANAGER':(d.mode||'advisory').toUpperCase();
 $('execv2badge').className='badge '+(d.apply_live?'live':'');
 $('execv2rows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="mono">${Number(x.age_seconds||0).toFixed(0)}s</td><td class="mono">${money(x.current_limit_price)}</td><td class="mono">${money(x.maker_target_price)}</td><td class="mono">${Number(x.move_bps||0).toFixed(1)} bps</td><td class="${x.recommend_reprice?'green':'amber'}">${x.recommend_reprice?'HERPRIJZEN':'wachten'} · ${esc(x.reason||'')}</td></tr>`).join(''):'<tr><td colspan="7" class="sub">Geen actieve orders om te beoordelen</td></tr>';
 let lastErr=errs.length?(' · laatste cancel-fout: '+esc(errs[0].strategy)+' '+esc(errs[0].market)+' / '+esc(errs[0].category)):'';
 $('execv2note').textContent=(d.apply_live?'Live stale-order manager actief':'Alleen advies')+' · orders gewijzigd: '+(d.live_orders_changed?'JA':'nee')+' · cancel-fouten laatste cyclus: '+errs.length+lastErr;
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
 $('routerrows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(names[x.key]||x.key)}</b></td><td>${esc(x.best.market)}</td><td class="mono">${Number(x.best.score||0).toFixed(1)}</td><td class="mono">${Number(x.best.signal_strength||0).toFixed(1)}</td><td class="mono">${esc(x.best.signal_direction||'—')}</td><td class="mono">${Number(x.best.spread_bps||0).toFixed(1)} bps</td><td class="mono">${Number(x.best.momentum_pct||0).toFixed(3)}%</td><td class="mono">${money(x.best.liquidity_eur)}</td></tr>`).join(''):'<tr><td colspan="8" class="sub">Nog onvoldoende router-data</td></tr>';
 $('routernote').textContent=scanned+' van '+configured+' beschikbare EUR-markten gescand · cap '+maxm+' · auto-discovery '+(d.auto_discover_eur?'AAN':'uit')+' · live orders verzonden: '+(d.live_orders_sent?'JA':'nee')+(d.runtime_error?' · fout: '+d.runtime_error:'');
}
function renderUniverse(d){
 const bv=d.bitvavo||{},cb=d.coinbase||{},rows=d.top_quality_candidates||[];
 $('unibv').textContent=Number(bv.tradable||0);
 $('unicb').textContent=Number(cb.tradable||0);
 $('unicrypto').textContent=Number(bv.crypto_crypto||0)+Number(cb.crypto_crypto||0);
 $('unioverlap').textContent=Number(d.exact_cross_venue_overlap||0);
 $('uniccoverlap').textContent=Number(d.overlap_crypto_crypto||0);
 $('unierror').textContent=d.error?'ERROR':'OK';$('unierror').className='v '+(d.error?'red':'green');
 $('universebadge').textContent=d.live_orders_sent?'ERROR':'READ ONLY';
 $('universebadge').className='badge '+(d.live_orders_sent?'':'ok');
 $('universerows').innerHTML=rows.length?rows.slice(0,12).map(x=>`<tr><td><b>${esc(x.venue)}</b></td><td>${esc(x.market)}</td><td>${esc(x.pair_type)}</td><td>${esc(x.quote)}</td><td class="mono">${Number(x.market_quality_score||0).toFixed(1)}</td><td class="mono">${x.spread_bps==null?'—':Number(x.spread_bps).toFixed(1)+' bps'}</td><td class="mono">${x.top_depth_eur==null?'—':money(x.top_depth_eur)}</td><td class="${x.live_execution_supported_now?'green':'amber'}">${x.live_execution_supported_now?'VALIDATED':'RESEARCH'}</td></tr>`).join(''):'<tr><td colspan="8" class="sub">Nog geen universe-data</td></tr>';
 $('universenote').textContent='Alle spotparen geïnventariseerd · Bitvavo crypto→crypto '+Number(bv.crypto_crypto||0)+' · Coinbase crypto→crypto '+Number(cb.crypto_crypto||0)+' · exacte venue-overlap '+Number(d.exact_cross_venue_overlap||0)+' · live orders door deze scanner: '+(d.live_orders_sent?'JA':'nee')+(d.runtime_error?' · fout: '+esc(d.runtime_error):'');
}
function renderFeeEfficiency(d){
 let rows=d.rows||[];
 $('feerows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="${Number(x.realized_net_pnl_eur||0)>=0?'green':'red'}">${money(x.realized_net_pnl_eur)}</td><td>${money(x.fees_eur)}</td><td class="${x.fee_drag_pct!=null&&Number(x.fee_drag_pct)>50?'amber':''}">${x.fee_drag_pct==null?'—':Number(x.fee_drag_pct).toFixed(1)+'%'}</td><td>${money(x.net_per_exit_eur)}</td><td>${esc(x.state||'—')}</td></tr>`).join(''):'<tr><td colspan="7" class="sub">Nog onvoldoende fill-data</td></tr>';
 $('feenote').textContent='Fee-efficiency is meetdata · live wijzigingen: '+(d.live_changes?'JA':'nee');
}
function renderFeeReality(d){
 const pct=v=>v==null?'—':Number(v).toFixed(3)+'%';
 $('actualmakerfee').textContent=pct(d.maker_fee_pct);
 $('actualtakerfee').textContent=pct(d.taker_fee_pct);
 $('feevolume').textContent=money(d.volume_30d_eur||0);
 $('feerealitybadge').textContent=d.error?'FEE DATA ERROR':'READ ONLY';
 $('feerealitybadge').className='badge '+(d.error?'':'ok');
 let rows=d.strategy_routes||[];
 $('feerealityrows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.order_mode)}</td><td>${esc(x.fee_class)}</td><td class="mono">${pct(x.fee_rate_pct_each_leg)}</td><td class="mono">${pct(x.two_leg_fee_floor_pct)}</td><td class="mono">${pct(x.cost_floor_with_configured_slippage_pct)}</td><td class="mono">${pct(x.research_required_gross_edge_pct)}</td></tr>`).join(''):'<tr><td colspan="7" class="sub">Geen fee-data beschikbaar</td></tr>';
 let cfg=d.configured_policy||{};
 $('feerealitynote').textContent=(d.error?('Fee lookup: '+esc(d.error)+' · fallback actief · '):'')+'Conservatieve fallback '+pct(cfg.required_gross_edge_pct)+' · route-specifieke fee-gates: '+(d.live_profit_gates_changed?'ACTIEF':'fallback')+' · postOnly maker-routes gebruiken maker-fee; Sniper gebruikt taker-fee.';
}
function renderAutonomy(d){
 let p=d.plan||{},rows=p.rows||[],armed=!!d.armed;
 $('autonomymode').textContent=armed?(p.apply_live?'AUTONOMOUS LIVE':'ARMED / SHADOW PLAN'):'WACHT OP LIVE ARM';
 $('autonomymode').className='badge '+(armed&&p.apply_live?'live':'');
 $('autonomybadge').textContent='SET → EXECUTE → LEARN → REPEAT';
 $('autonomyrows').innerHTML=rows.length?rows.map(x=>`<tr><td><b>${esc(x.strategy)}</b></td><td>${esc(x.current_market)}</td><td class="${x.desired_market!==x.current_market?'blue':''}">${esc(x.desired_market)}</td><td class="mini">${(x.allowed_markets||[]).includes('*')?'60-market scanner':esc((x.allowed_markets||[]).join(', ')||'router universe')}</td><td class="mono">${Number(x.market_score||0).toFixed(1)}</td><td class="mono">${Number(x.signal_strength||0).toFixed(1)} · ${esc(x.signal_direction||'—')}</td><td class="mono">${(Number(x.confidence||0)*100).toFixed(1)}%</td><td class="${x.entry_allowed?'green':'amber'}"><b>${x.entry_allowed?'OPEN':'WAIT'}</b></td><td class="mono">${money(x.recommended_order_eur)}</td><td class="${x.may_switch?'green':'amber'}">${x.may_switch?'JA':'nee'}</td><td>${esc(x.reason||'—')}</td></tr>`).join(''):'<tr><td colspan="11" class="sub">Nog geen autonomy-plan beschikbaar</td></tr>';
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
function renderFund(d){
 let r=d.risk||{},l=d.ledger||{},g=d.growth||{},stage=g.stage||{},tr=g.track_record||{},research=d.research||{},perf=d.performance||{},gov=d.governance||{},compliance=gov.compliance||{},investor=gov.investor_reporting||{},p=Math.max(0,Math.min(100,Number(r.target_progress_pct||0)));
 $('fundnav').textContent=money(r.nav_eur||0);
 $('fundtarget').textContent=money(r.target_nav_eur||100000);
 $('funddrawdown').textContent=Number(r.drawdown_pct||0).toFixed(2)+'%';
 $('funddrawdown').className='v '+(Number(r.drawdown_pct||0)>4?'red':Number(r.drawdown_pct||0)>2?'amber':'green');
 $('fundriskcapital').textContent=money(r.risk_capital_available_eur||0);
 $('fundriskcapital').className='v '+(Number(r.risk_capital_available_eur||0)>0?'green':'amber');
 $('fundprogress').textContent=p.toFixed(3)+'%';
 $('fundprogressbar').style.width=p+'%';
 $('fundfloor').textContent=(r.capital_floor_armed?'ARMED · ':'NIET GEACTIVEERD · ')+money(r.protected_capital_floor_eur||25000);
 $('fundzone').textContent=money(r.protected_zone_eur||0);
 $('fundgross').textContent=money(r.gross_exposure_eur||0)+' · '+Number(r.gross_exposure_pct||0).toFixed(2)+'%';
 $('funddelever').textContent=money(r.required_deleveraging_eur||0);
 $('funddelever').className=Number(r.required_deleveraging_eur||0)>0?'red':'green';
 let navAge=r.nav_age_seconds==null?'—':Number(r.nav_age_seconds).toFixed(1)+'s';
 $('fundnavverified').textContent=(r.nav_verified?'VERIFIED':'BLOCKED')+' · '+esc(r.nav_source||'unknown')+' · '+navAge;
 $('fundnavverified').className=r.nav_verified?'green':'red';
 $('fundstage').textContent=esc(stage.label||stage.key||'—');
 $('fundnext').textContent=g.next_milestone_eur==null?'TRACK RECORD':money(g.next_milestone_eur);
 $('fundtrack').textContent=(g.verified_track_record?'VERIFIED':'BUILDING')+' · '+Number(tr.days||0).toFixed(1)+'/'+Number(tr.minimum_days||365)+' dagen · '+Number(tr.fills||0)+'/'+Number(tr.minimum_fills||100)+' fills';
 $('fundtrack').className=g.verified_track_record?'green':'amber';
 $('fundroles').textContent=(g.active_roles||[]).join(' · ')||'—';
 $('fundledger').textContent=l.valid===true?'VALID · '+Number(l.count||0)+' events':'CONTROLEREN';
 $('fundledger').className=l.valid===true?'green':'red';
 let preservation=!!r.capital_preservation_mode,armed=!!r.capital_floor_armed,reached=!!r.target_reached;
 $('fundmode').textContent=preservation?'CAPITAL PRESERVATION':armed?'FLOOR ARMED':reached?'TARGET REACHED':'GROEI';
 $('fundmode').className='badge '+(preservation?'':armed?'ok':'live');
 $('fundbadge').textContent=armed?'€25K FLOOR ARMED':'FUND CORE';
 $('fundbadge').className='badge '+(armed?'ok':'');
 $('fundnote').textContent=preservation
   ?'Nieuwe risicoverhogende orders geblokkeerd; alleen risicoverlaging toegestaan totdat exposure weer binnen surplus capital valt.'
   :armed
     ?'€25.000 floor is permanent gelatcht; nieuwe exposure mag alleen uit vermogen boven de beschermde zone komen.'
     :(r.nav_verified
       ?'Groei naar €50.000 onder automatische stage-limieten; bij €25.000 wordt de protected-capital floor permanent gelatcht; het target verhoogt nooit automatisch het risico.'
       :'Live NAV is niet geverifieerd of te oud: nieuwe risicoverhogende orders blijven fail-closed.');
 let agents=research.agents||[];
 $('prototypeAgents').textContent=Number(research.agent_count||0)+'/9';
 $('prototypeCoverage').textContent=Number(research.signal_coverage_pct||0).toFixed(1)+'%';
 $('prototypeFills').textContent=Number(perf.fill_count||0);
 $('prototypePnl').textContent=money(perf.realized_net_pnl_eur||0);
 $('prototypePnl').className='v '+(Number(perf.realized_net_pnl_eur||0)>=0?'green':'red');
 $('prototypeWindows').textContent=money(perf.realized_net_pnl_24h_eur||0)+' / '+money(perf.realized_net_pnl_7d_eur||0)+' / '+money(perf.realized_net_pnl_30d_eur||0);
 $('prototypePf').textContent=perf.profit_factor==null?'NOG GEEN VERLIESBASIS':Number(perf.profit_factor).toFixed(3);
 $('prototypeCompliance').textContent=compliance.all_internal_controls_passed?'INTERNAL CONTROLS PASS':'CONTROLEREN';
 $('prototypeCompliance').className=compliance.all_internal_controls_passed?'green':'red';
 $('prototypeInvestor').textContent=esc(investor.status||'BUILDING_VERIFIED_TRACK_RECORD');
 $('prototypeInvestor').className=investor.diligence_ready?'green':'amber';
 $('prototypeBadge').textContent=investor.diligence_ready?'DILIGENCE READY':'BUILDING TRACK RECORD';
 $('prototypeBadge').className='badge '+(investor.diligence_ready?'ok':'');
 $('prototypeNote').textContent=investor.diligence_ready
   ?'Verified track record gate gehaald; third-party capital acceptance blijft uit totdat juridische/compliance setup afzonderlijk is voltooid.'
   :'€50 → €500 → €5.000 → €50.000 → verified track record. Groei verandert de riskregels niet buiten de automatische stage-envelope.';
 $('prototypeAgentRows').innerHTML=agents.length?agents.map(x=>`<tr><td><b>${esc(x.label||x.key)}</b></td><td class="${x.state==='ACTIVE'||x.state==='CONTROL'?'green':x.state==='STALE'?'amber':'sub'}">${esc(x.state||'—')}</td><td>${Number(x.signal_count||0)}</td><td>${(Number(x.mean_confidence||0)*100).toFixed(1)}%</td><td>${Number(x.mean_score||0).toFixed(1)}</td></tr>`).join(''):'<tr><td colspan="5" class="sub">Geen research-agent status</td></tr>';
 drawFundEquity(perf.equity_curve||[]);
}
function drawFundEquity(rows){
 const canvas=$('prototypeEquity'); if(!canvas)return;
 const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
 canvas.width=Math.max(1,Math.floor(rect.width*dpr));canvas.height=Math.max(1,Math.floor(92*dpr));
 const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
 let vals=(rows||[]).map(x=>Number(x.equity_eur)).filter(Number.isFinite);
 if(!vals.length){ctx.fillStyle='#7f8ca3';ctx.font=(12*dpr)+'px sans-serif';ctx.fillText('Nog geen durable fills voor equity curve',8*dpr,28*dpr);return}
 let lo=Math.min(...vals),hi=Math.max(...vals);if(hi===lo){hi=lo+1}
 ctx.lineWidth=1.5*dpr;ctx.strokeStyle='#58a6ff';ctx.beginPath();
 vals.forEach((v,i)=>{let x=(i/Math.max(1,vals.length-1))*(canvas.width-12*dpr)+6*dpr,y=canvas.height-6*dpr-((v-lo)/(hi-lo))*(canvas.height-12*dpr);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});
 ctx.stroke();
}
function renderFundAutomation(d){
 let rules=d.hard_rules||{},reg=d.market_regime||{},latest=(d.latest_research||[])[0]||{},mc=latest.monte_carlo||{};
 $('fundAutoPolicy').textContent='SPOT ONLY · SCORE '+esc(rules.live_entry_score_operator||'>')+Number(rules.live_entry_score_threshold||85).toFixed(0)+' · DD '+Number(rules.max_portfolio_drawdown_pct||10).toFixed(0)+'%';
 $('fundAutoPolicy').className='green';
 $('fundAutoRegime').textContent=esc(reg.state||'WAITING')+(reg.market?' · '+esc(reg.market):'')+(reg.score!=null?' · score '+Number(reg.score).toFixed(1):'');
 let when=d.last_research_at?new Date(Number(d.last_research_at)*1000).toLocaleString():'nog geen run';
 $('fundAutoResearch').textContent=(d.monte_carlo_simulations||10000)+' sims · '+when+' · '+((d.last_research_markets||[]).join(', ')||'wacht op marktdata');
 if(mc.risk_of_ruin_pct!=null){
   $('fundAutoMonte').textContent='ruin '+Number(mc.risk_of_ruin_pct).toFixed(2)+'% · profit '+Number(mc.probability_of_profit_pct||0).toFixed(2)+'% · P50 '+money((mc.terminal_capital||{}).p50||0);
 }else{
   $('fundAutoMonte').textContent='Nog geen automatische Monte Carlo-snapshot';
 }
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
 $('orderFilledCount').textContent=filled;$('orderCanceledCount').textContent=canceled;
 $('activityBadge').textContent=(d.total_returned||0)+' recent';
 const when=ts=>ts?new Date(Number(ts)*1000).toLocaleString():'—';
 const chip=s=>{s=String(s||'unknown').toLowerCase();let k=['filled'].includes(s)?'filled':['canceled','cancelled','expired'].includes(s)?'canceled':['rejected','error','blocked'].includes(s)?'error':'open';return '<span class="status-chip '+k+'">'+esc(s)+'</span>'};
 $('orderactivity').innerHTML=rows.length?rows.map(x=>`<tr><td class="mono">${esc(when(x.created_at))}</td><td><b>${esc(x.strategy)}</b></td><td>${esc(x.market)}</td><td class="${x.side==='buy'?'side-buy':'side-sell'}">${esc((x.side||'').toUpperCase())}</td><td>${esc(x.order_type||'—')}</td><td class="mono">${num(x.amount)}</td><td class="mono">${x.price?money(x.price):'MARKET'}</td><td class="mono">${esc(x.fill_count||0)} · ${num(x.filled_amount||0)}</td><td>${chip(x.status)}</td></tr>`).join(''):'<tr><td colspan="9" class="sub">Nog geen orders in het journal</td></tr>';
 $('orderactivitynote').textContent=(d.total_returned||0)+' orders getoond · nieuwste eerst · historische foutstatussen in deze 100: '+errors+' · de rode KPI bovenaan telt alleen de laatste 3 uur';
}
function renderBitvavo(d,e){let ok=d.authenticated_probe===true;$('fusioncred').textContent=d.credentials_present?'aanwezig':'ontbreekt';$('fusioncred').className=d.credentials_present?'green':'red';$('fusionauth').textContent=ok?'geslaagd':'mislukt';$('fusionauth').className=ok?'green':'red';$('fusionendpoint').textContent='account + EUR balance';$('fusionmode').textContent=(e?.mode||'paper')+' · live '+(e?.live_execution_capability||'uit');$('fusionchecked').textContent=new Date().toLocaleTimeString();$('fusionnote').textContent=ok?(d.passed?'Bitvavo securitycontrole geslaagd.':'Bitvavo authenticatie geslaagd; aanvullende safety-checks zijn nog niet compleet.'):'Bitvavo read-only authenticatie niet geslaagd: '+((d.errors||[]).join(', ')||'onbekend');$('safetymode').textContent=e?.mode||'paper';$('fusionlive').textContent=e?.live_execution_capability||'uit';$('emergencystop').textContent=e?.emergency_stop?'ACTIEF':'niet actief'}
function setSectionError(label,error){$('apierror').textContent=label+': '+(error?.message||'niet beschikbaar')}
function renderLiveReadiness(d){
  const resume=!!d.resume_mode;
  $('liveready').textContent=d.ready?(resume?'READY TO RESUME':'READY'):'NOT READY';
  $('liveready').className=d.ready?'green':'amber';
  $('livecheck').textContent=d.ready
    ? (resume
      ? 'Bestaande Bitvavo-orders zijn aantoonbaar bot-owned en met het duurzame journal gereconcileerd. Hervatten blijft een expliciete operatoractie.'
      : 'Alle server-side voorwaarden zijn aanwezig. Activeren blijft een expliciete operatoractie.')
    : 'Nog niet klaar: '+Object.entries(d.gates).filter(([_,v])=>!v).map(([k])=>k).join(', ');
  const armed=!!d.armed;
  $('livebtn').disabled=!d.ready||armed;$('liveaction').disabled=!d.ready||armed;$('livestop').style.display=armed?'inline-block':'none';
  if(armed){
    $('liveready').textContent='ARMED · LIVE';$('liveready').className='blue';
    $('livecheck').textContent='Live execution is actief voor deze runtime. Nieuwe orders blijven onder alle risk-, allocation- en profit-gates.';
    $('notice').textContent='LIVE ACTIEF · Nieuwe orders mogen alleen door als autonomy, profit, allocation en exchange-gates tegelijk slagen.';
    $('notice').style.borderLeftColor='var(--green)';$('notice').style.background='#102b24';$('notice').style.color='#bfeedd';
  }else if(d.ready){
    $('notice').textContent='LIVE UIT / READY · Een Railway-deploy of herstart reset de runtime-arm automatisch. Bestaande exchange-orders blijven beheerd; nieuwe orders vereisen opnieuw expliciete activatie.';
    $('notice').style.borderLeftColor='var(--amber)';$('notice').style.background='#2c2514';$('notice').style.color='#ead9ad';
  }else{
    $('notice').textContent='LIVE GEBLOKKEERD · Niet alle server-side veiligheidsvoorwaarden zijn groen. Nieuwe live orders zijn uitgeschakeld.';
    $('notice').style.borderLeftColor='var(--red)';$('notice').style.background='#31151d';$('notice').style.color='#ffd3d8';
  }
}
async function refreshLiveReadiness(){
 try{renderLiveReadiness(await get('/api/live/readiness'))}
 catch(e){$('liveready').textContent='ONBEKEND';$('livecheck').textContent=e.message;$('livebtn').disabled=true;$('liveaction').disabled=true}
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
  const ctl=prompt('Vul je AUTOTRADER_CONTROL_TOKEN in. Deze wordt niet opgeslagen.');
  if(!ctl) return;
  const phrase=prompt('Bevestig live orders door exact I_UNDERSTAND_LIVE_ORDERS in te vullen.');
  if(phrase!=='I_UNDERSTAND_LIVE_ORDERS') return;
  const r=await fetch('/api/live/activate',{method:'POST',headers:{...headers(),'Content-Type':'application/json','X-Autotrader-Token':ctl},body:JSON.stringify({confirmation:phrase})});
  const d=await r.json(); if(!r.ok) throw Error(d.detail?.message||d.detail||'Activering geweigerd');
  await refreshLiveReadiness(); alert('Live Trading is geactiveerd. De bot kan nu nieuwe orders uitvoeren.');
 }catch(e){alert(e.message||'Live activering mislukt');}
}
async function deactivateLive(){
 try{
  const ctl=prompt('Vul je AUTOTRADER_CONTROL_TOKEN in. Deze wordt niet opgeslagen.');
  if(!ctl) return;
  const r=await fetch('/api/live/deactivate',{method:'POST',headers:{...headers(),'X-Autotrader-Token':ctl}});
  const d=await r.json(); if(!r.ok) throw Error(d.detail||'Stoppen mislukt');
  await refreshLiveReadiness(); alert('Live Trading is gestopt. Nieuwe orders worden niet meer uitgevoerd.');
 }catch(e){alert(e.message||'Stoppen mislukt');}
}
async function refresh(){
 let now=new Date().toLocaleString();
 $('last').textContent='Bijwerken…';$('apierror').textContent='';
 try{
  let snap=await get('/api/dashboard/snapshot'),sections=snap.sections||{};
  let section=(key)=>{let x=sections[key];return x&&x.ok?{status:'fulfilled',value:x.data}:{status:'rejected',reason:Error((x&&x.error)||'niet beschikbaar')}};
  let entries=[
   section('paper_report'),section('execution_status'),section('pnl_summary'),section('health'),section('bitvavo_security'),
   section('risk_status'),section('fund'),section('fund_automation'),section('markets_overview'),section('strategies'),section('bitvavo_live_state'),section('live_pnl'),
   section('coinbase_security'),section('coinbase_live_state'),section('arbitrage'),section('shadow'),section('allocator'),
   section('orders'),section('execution_v2'),section('opportunities'),section('fee_efficiency'),section('portfolio_goal'),
   section('binance_reference'),section('autonomy'),section('risk_lab'),section('three_hour'),section('fees_live'),
   section('universe_summary'),section('live_readiness')
  ];
  let [r,e,s,h,f,k,fund,fa,m,a,v,p,cb,cbb,arb,sh,al,oa,ev2,op,fe,goal,bref,auto,rl,threeh,fr,uni,lr]=entries;
  let fail=(entry,label)=>{if(entry.status==='rejected')setSectionError(label,entry.reason)};
  if(r.status==='fulfilled')renderReport(r.value);else fail(r,'Portfolio');
  if(e.status==='fulfilled')renderExec(e.value);else fail(e,'Execution');
  if(s.status==='fulfilled')renderStrategies(s.value);else fail(s,'PnL');
  if(h.status==='fulfilled'){$('ticker').textContent=h.value.runtime?.ticker_running?'actief':'gestopt';$('updated').textContent=new Date().toLocaleTimeString();$('healthbar').style.width=h.value.runtime?.last_tick_error?'25%':'100%'}else fail(h,'Runtime');
  if(f.status==='fulfilled')renderBitvavo(f.value,e.status==='fulfilled'?e.value:{});else fail(f,'Bitvavo');
  if(k.status==='fulfilled')renderRisk(k.value);else fail(k,'Risk');
  if(fund.status==='fulfilled')renderFund(fund.value);else fail(fund,'Fund Core');
  if(fa.status==='fulfilled')renderFundAutomation(fa.value);else fail(fa,'Autonomous Fund');
  if(m.status==='fulfilled')renderMarkets(m.value);else fail(m,'Markten');
  if(a.status==='fulfilled')renderAgents(a.value);else fail(a,'Agents');
  if(v.status==='fulfilled')renderLiveState(v.value);else fail(v,'Open orders');
  if(p.status==='fulfilled')renderProfit(p.value);else fail(p,'Profit supervisor');
  if(cb.status==='fulfilled')renderCoinbase(cb.value);else fail(cb,'Coinbase');
  if(cbb.status==='fulfilled')renderCoinbaseBalances(cbb.value);else fail(cbb,'Coinbase saldo');
  if(arb.status==='fulfilled')renderArbitrage(arb.value);else fail(arb,'Arbitrage');
  if(sh.status==='fulfilled')renderShadow(sh.value);else fail(sh,'Shadow bots');
  if(al.status==='fulfilled')renderAllocator(al.value);else fail(al,'Allocator v2');
  if(oa.status==='fulfilled')renderOrderActivity(oa.value);else fail(oa,'Orderhistorie');
  if(ev2.status==='fulfilled')renderExecutionV2(ev2.value);else fail(ev2,'Execution v2');
  if(op.status==='fulfilled')renderOpportunities(op.value);else fail(op,'Opportunity Router');
  if(fe.status==='fulfilled')renderFeeEfficiency(fe.value);else fail(fe,'Fee Efficiency');
  if(goal.status==='fulfilled')renderGoal(goal.value);else fail(goal,'€25k doel');
  if(bref.status==='fulfilled')renderBinanceReference(bref.value);else fail(bref,'Binance reference');
  if(auto.status==='fulfilled')renderAutonomy(auto.value);else fail(auto,'Autonomy');
  if(rl.status==='fulfilled')renderRiskLab(rl.value);else fail(rl,'Risk Lab');
  if(threeh.status==='fulfilled')renderThreeHour(threeh.value);else fail(threeh,'3-uurs rapport');
  if(fr.status==='fulfilled')renderFeeReality(fr.value);else fail(fr,'Fee Reality');
  if(uni.status==='fulfilled')renderUniverse(uni.value);else fail(uni,'Full Market Universe');
  if(lr.status==='fulfilled')renderLiveReadiness(lr.value);else fail(lr,'Live readiness');
 }catch(e){setSectionError('Dashboard',e)}
 $('last').textContent='Bijgewerkt '+now
}
function connect(){try{let scheme=location.protocol==='https:'?'wss':'ws';let credential=apiKey||token;if(!credential){$('socket').textContent='auth vereist';return}socket=new WebSocket(`${scheme}://${location.host}/ws/paper`,['at-v1',credential]);socket.onopen=()=>{$('socket').textContent='verbonden';$('socket').className='green'};socket.onmessage=e=>{try{if(($('mode').textContent||'').toLowerCase()!=='live')renderReport(JSON.parse(e.data))}catch(_){}};socket.onclose=()=>{$('socket').textContent='herstellen…';setTimeout(connect,4000)}}catch(_){$('socket').textContent='niet beschikbaar'}}
if(token||apiKey){$('login').classList.add('hidden');$('app').classList.remove('hidden');refresh();connect()}
setInterval(()=>{if(!$('app').classList.contains('hidden'))refresh()},15000);
</script></body></html>'''


def dashboard_html() -> str:
    return DASHBOARD_HTML
