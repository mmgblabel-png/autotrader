"""Local-only Bitvavo credential validation UI.

Credentials are accepted per request, used for one authenticated GET /balance,
and discarded. They are never persisted, returned, or placed in URLs.
Run this app bound to 127.0.0.1 only.
"""
from __future__ import annotations

import html
import urllib.error
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from autotrader.connectors.bitvavo import BitvavoAdapter, BitvavoError


class Credentials(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)
    api_secret: str = Field(min_length=8, max_length=256)
    symbol: str | None = Field(default=None, max_length=12)


app = FastAPI(title="Bitvavo local validator", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bitvavo veilige verbindingstest</title>
<style>
body{font:16px system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;background:#10131a;color:#edf2f7}main{background:#1b2230;padding:28px;border-radius:16px}label{display:block;margin-top:16px}input{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:white}button{margin-top:22px;padding:12px 18px;border:0;border-radius:8px;background:#45d483;color:#07130d;font-weight:700;cursor:pointer}button:disabled{opacity:.6;cursor:wait}pre{white-space:pre-wrap;background:#0f172a;padding:14px;border-radius:8px;margin-top:20px}.note{color:#cbd5e1;font-size:.94rem}.ok{color:#86efac}.err{color:#fca5a5}.hint{margin-top:10px;color:#cbd5e1;font-size:.9rem}
</style></head><body><main>
<h1>Bitvavo verbinding testen</h1>
<p class="note">Deze pagina draait alleen lokaal. Je API-secret wordt één keer gebruikt voor een private saldo-aanvraag en wordt niet opgeslagen, teruggestuurd of in de URL geplaatst.</p>
<form id="f" method="post" action="/api/validate"><label>Bitvavo API-key<input name="api_key" autocomplete="off" required></label>
<label>Bitvavo API-secret<input name="api_secret" type="password" autocomplete="off" required></label>
<label>Optioneel asset-symbool<input name="symbol" placeholder="EUR of BTC" maxlength="12"></label>
<button id="submit">Valideer en haal saldo op</button></form><p id="hint" class="hint">Je gegevens worden na elke poging uit het formulier gewist.</p><pre id="out" role="status" aria-live="polite">Nog niet getest.</pre>
<script>
const f=document.querySelector('#f'),out=document.querySelector('#out'),submit=document.querySelector('#submit'),hint=document.querySelector('#hint');
const messages={invalid_credentials:'De API-key of API-secret is ongeldig, verlopen of heeft geen saldo-leestoegang.',network_error:'Bitvavo was tijdelijk niet bereikbaar. Controleer internetverbinding en probeer opnieuw.',invalid_response:'Bitvavo gaf een onverwachte respons. Probeer later opnieuw.',invalid_input:'Controleer de invoer: API-key en API-secret zijn verplicht.',bitvavo_http_error:'Bitvavo heeft de aanvraag afgewezen. Controleer sleutelrechten en IP-beperking.',bitvavo_error:'De Bitvavo-verbindingstest is mislukt.'};
f.addEventListener('submit',async e=>{e.preventDefault();out.textContent='Bezig…';out.className='';hint.textContent='De sleutel wordt alleen voor deze aanvraag gebruikt.';submit.disabled=true;
 const data=Object.fromEntries(new FormData(f)); if(!data.symbol)data.symbol=null;
 try{const r=await fetch('/api/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let j=null;try{j=await r.json();}catch{j={detail:{code:'invalid_response',message:'De server gaf geen geldige JSON-respons.'}};} if(r.ok){out.textContent=JSON.stringify(j,null,2);out.className='ok';}else{const d=typeof j.detail==='object'?j.detail:{code:'bitvavo_error'};out.textContent='Niet gevalideerd\n\n'+(messages[d.code]||messages.bitvavo_error);out.className='err';}}catch(err){out.textContent='Lokale verbinding met de validatiepagina mislukt. Controleer of de pagina nog draait.';out.className='err';}finally{f.reset();submit.disabled=false;}
});
</script></main></body></html>"""


@app.post("/api/validate")
def validate(credentials: Credentials) -> dict[str, Any]:
    # No credential is logged, returned, persisted, or put into a URL.
    try:
        adapter = BitvavoAdapter(api_key=credentials.api_key, api_secret=credentials.api_secret)
        balances = adapter.balance(credentials.symbol or None)
        return {
            "ok": True,
            "mode": "shadow",
            "dry_run": True,
            "permission_test": "private balance read succeeded",
            "balances": balances,
            "real_order_sent": False,
        }
    except BitvavoError as exc:
        code = exc.category
        status = 401 if code == "invalid_credentials" else 502
        raise HTTPException(
            status_code=status,
            detail={"code": code, "message": "Validation failed; credentials were not stored."},
        ) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_input", "message": "Validation failed; credentials were not stored."},
        ) from exc
