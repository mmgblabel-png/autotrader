"""Public AIHF closed-beta portal.

This page performs wallet authentication and read-only entitlement checks only.
It never requests a seed phrase/private key and never submits token approvals,
locks, trades, or other blockchain transactions.
"""
from __future__ import annotations


def aihf_portal_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI HedgeFund Ecosystem — Closed Beta</title>
<style>
:root{color-scheme:dark;--bg:#071016;--panel:#0d1822;--edge:#203342;--text:#edf5fa;--muted:#91a7b7;--gold:#d7ad5c;--cyan:#49d6ff;--good:#63d69f;--warn:#ffcb6b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 70% 0,#132838 0,#071016 38%,#050a0e 100%);font-family:Inter,system-ui,sans-serif;color:var(--text)}
.wrap{max-width:1100px;margin:0 auto;padding:36px 20px 70px}.top{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:28px}
.brand{font-weight:800;letter-spacing:.04em;font-size:20px}.brand b{color:var(--gold)}.badge{border:1px solid var(--edge);padding:7px 11px;border-radius:999px;color:var(--muted);font-size:12px}
.hero{border:1px solid var(--edge);background:linear-gradient(145deg,rgba(13,24,34,.96),rgba(8,16,23,.96));border-radius:18px;padding:30px;box-shadow:0 30px 80px rgba(0,0,0,.3)}
h1{margin:0 0 12px;font-size:clamp(32px,6vw,64px);line-height:.98;max-width:850px}.accent{color:var(--cyan)}p{color:var(--muted);line-height:1.6;max-width:800px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}button{appearance:none;border:1px solid var(--edge);background:#122330;color:var(--text);padding:12px 16px;border-radius:10px;font-weight:700;cursor:pointer}button.primary{background:var(--cyan);color:#001018;border-color:var(--cyan)}button:disabled{opacity:.45;cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:18px}.card{border:1px solid var(--edge);background:rgba(13,24,34,.84);border-radius:14px;padding:18px}.card h3{margin:0 0 8px}.tier{font-size:28px;font-weight:800}.reader{color:#9bd5ff}.pro{color:var(--gold)}.quant{color:#cb8cff}
.status{margin-top:18px;border:1px solid var(--edge);border-radius:14px;padding:16px;background:#09131b}.status strong{color:var(--good)}pre{white-space:pre-wrap;word-break:break-word;color:#b9d0df;margin:8px 0 0;font-size:12px}
.note{margin-top:22px;padding:14px 16px;border-left:3px solid var(--warn);background:rgba(255,203,107,.06);color:#d6c59f;font-size:13px}
@media(max-width:760px){.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top"><div class="brand"><b>MMinc</b> · AI HedgeFund Ecosystem</div><div class="badge">Polygon Amoy · closed beta</div></div>
  <section class="hero">
    <h1>AI HedgeFund <span class="accent">HQ</span></h1>
    <p>The web entitlement layer for the Sandbox AI HedgeFund HQ. Connect a wallet, sign a non-transaction authentication message, and read the live AIHF Access Vault tier. This page does not place trades or move funds.</p>
    <div class="actions">
      <button class="primary" id="connect">Connect wallet</button>
      <button id="refresh" disabled>Refresh entitlement</button>
      <button id="pass" disabled>Check Sandbox Pass</button>
    </div>
    <div class="grid">
      <div class="card"><div class="tier reader">Reader</div><h3>100 AIHF locked</h3><p>Research Floor, research feed and Shadow Agent education.</p></div>
      <div class="card"><div class="tier pro">Pro</div><h3>1,000 AIHF locked</h3><p>Pro Strategy Lab, premium dashboard and deeper analytics.</p></div>
      <div class="card"><div class="tier quant">Quant</div><h3>10,000 AIHF locked</h3><p>Quant Vault, advanced strategy tooling and creator/API entitlements.</p></div>
    </div>
    <div class="status"><strong id="headline">Not connected</strong><pre id="details">Waiting for wallet authentication.</pre></div>
    <div class="note">AIHF is designed as a utility/access token. No dividend, profit share, guaranteed return, AutoTrader NAV claim, or trading advantage is provided. Sandbox Passes are presentation credentials; sensitive access is always re-checked against the live vault.</div>
  </section>
</div>
<script>
const $=id=>document.getElementById(id);
let wallet='',session=sessionStorage.getItem('aihf_session')||'';
const api=async(path,opts={})=>{
  const headers={'Accept':'application/json','Content-Type':'application/json',...(opts.headers||{})};
  if(session)headers.Authorization='Bearer '+session;
  const r=await fetch(path,{...opts,headers});
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(data.detail||('HTTP '+r.status));
  return data;
};
const show=(title,data)=>{$('headline').textContent=title;$('details').textContent=typeof data==='string'?data:JSON.stringify(data,null,2)};
async function ensureAmoy(){
  const chain=await ethereum.request({method:'eth_chainId'});
  if(chain.toLowerCase()==='0x13882')return true;
  try{await ethereum.request({method:'wallet_switchEthereumChain',params:[{chainId:'0x13882'}]});return true}
  catch(e){show('Switch to Polygon Amoy','Your wallet must have Polygon Amoy configured (chain ID 80002) before beta authentication.');return false}
}
async function connect(){
  try{
    if(!window.ethereum)throw new Error('No injected EVM wallet detected. Open with MetaMask or another compatible wallet.');
    const accounts=await ethereum.request({method:'eth_requestAccounts'});
    wallet=accounts[0];
    if(!await ensureAmoy())return;
    const challenge=await api('/api/ecosystem/auth/nonce',{method:'POST',body:JSON.stringify({address:wallet})});
    const signature=await ethereum.request({method:'personal_sign',params:[challenge.message,wallet]});
    const verified=await api('/api/ecosystem/auth/verify',{method:'POST',body:JSON.stringify({address:wallet,nonce:challenge.nonce,message:challenge.message,signature})});
    session=verified.access_token;sessionStorage.setItem('aihf_session',session);
    $('refresh').disabled=false;$('pass').disabled=false;
    await refresh();
  }catch(e){show('Authentication failed',e.message)}
}
async function refresh(){
  try{const d=await api('/api/ecosystem/access');show('Live entitlement: '+d.tier,d)}
  catch(e){show('Entitlement unavailable',e.message)}
}
async function pass(){
  try{const d=await api('/api/ecosystem/sandbox/pass-eligibility');show('Sandbox Pass eligibility',d)}
  catch(e){show('Pass check unavailable',e.message)}
}
$('connect').addEventListener('click',connect);$('refresh').addEventListener('click',refresh);$('pass').addEventListener('click',pass);
api('/api/ecosystem/status').then(s=>{if(!s.wallet_auth_configured)show('Closed beta not configured','AIHF wallet-session secret has not been configured on this environment yet.')}).catch(()=>{});
</script>
</body>
</html>"""
