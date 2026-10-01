"""Read-only perpetual futures market data for research/shadow agents.

No authentication, wallet, order placement or signing code exists in this
module. Hyperliquid is the primary public feed because one metadata request
returns mark price, oracle price, funding and open interest for the perp
universe. Binance USD-M mark-price data is used only as a read-only fallback.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Callable


class PerpetualMarketDataError(RuntimeError):
    pass


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default


class PerpetualPublicMarketData:
    HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
    BINANCE_USDM_PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

    def __init__(
        self,
        *,
        timeout: float = 3.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.timeout = max(0.5, float(timeout))
        self._opener = opener or urllib.request.urlopen

    def _json_request(self, request: urllib.request.Request) -> Any:
        try:
            with self._opener(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
            return json.loads(body)
        except Exception as exc:
            raise PerpetualMarketDataError(type(exc).__name__) from exc

    def _hyperliquid(self, coins: list[str]) -> dict[str, Any]:
        body = json.dumps({"type": "metaAndAssetCtxs"}).encode("utf-8")
        request = urllib.request.Request(
            self.HYPERLIQUID_INFO_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "AutoTrader/1.0"},
        )
        payload = self._json_request(request)
        if not isinstance(payload, list) or len(payload) < 2:
            raise PerpetualMarketDataError("hyperliquid_schema")
        meta, contexts = payload[0], payload[1]
        universe = (meta or {}).get("universe") if isinstance(meta, dict) else None
        if not isinstance(universe, list) or not isinstance(contexts, list):
            raise PerpetualMarketDataError("hyperliquid_schema")

        wanted = {str(c).upper().strip() for c in coins if str(c).strip()}
        rows: list[dict[str, Any]] = []
        for idx, instrument in enumerate(universe):
            if not isinstance(instrument, dict) or idx >= len(contexts):
                continue
            coin = str(instrument.get("name") or "").upper().strip()
            if not coin or coin not in wanted:
                continue
            ctx = contexts[idx] if isinstance(contexts[idx], dict) else {}
            mark = _float(ctx.get("markPx") or ctx.get("midPx"))
            oracle = _float(ctx.get("oraclePx"), mark)
            if mark <= 0:
                continue
            rows.append({
                "coin": coin,
                "symbol": f"{coin}-USD-PERP",
                "source": "hyperliquid_public",
                "mark_price": mark,
                "oracle_price": oracle if oracle > 0 else mark,
                "funding_rate": _float(ctx.get("funding")),
                "open_interest": _float(ctx.get("openInterest")),
                "day_notional_volume_usd": _float(ctx.get("dayNtlVlm")),
                "max_venue_leverage": _float(instrument.get("maxLeverage"), 1.0),
                "timestamp": time.time(),
            })
        if not rows:
            raise PerpetualMarketDataError("hyperliquid_no_requested_markets")
        return {
            "source": "hyperliquid_public",
            "markets": rows,
            "live_orders_sent": False,
            "authenticated": False,
        }

    def _binance_usdm(self, coins: list[str]) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for raw_coin in coins:
            coin = str(raw_coin).upper().strip()
            if not coin:
                continue
            symbol = f"{coin}USDT"
            url = self.BINANCE_USDM_PREMIUM_URL + "?" + urllib.parse.urlencode({"symbol": symbol})
            request = urllib.request.Request(
                url,
                method="GET",
                headers={"Accept": "application/json", "User-Agent": "AutoTrader/1.0"},
            )
            payload = self._json_request(request)
            if not isinstance(payload, dict):
                continue
            mark = _float(payload.get("markPrice"))
            index = _float(payload.get("indexPrice"), mark)
            if mark <= 0:
                continue
            rows.append({
                "coin": coin,
                "symbol": f"{coin}-USDT-PERP",
                "source": "binance_usdm_public_fallback",
                "mark_price": mark,
                "oracle_price": index if index > 0 else mark,
                "funding_rate": _float(payload.get("lastFundingRate")),
                "open_interest": 0.0,
                "day_notional_volume_usd": 0.0,
                "max_venue_leverage": 1.0,
                "timestamp": time.time(),
            })
        if not rows:
            raise PerpetualMarketDataError("binance_no_requested_markets")
        return {
            "source": "binance_usdm_public_fallback",
            "markets": rows,
            "live_orders_sent": False,
            "authenticated": False,
        }

    def snapshots(self, coins: list[str]) -> dict[str, Any]:
        """Fetch public perpetual snapshots with a second public venue fallback."""
        try:
            payload = self._hyperliquid(coins)
            payload["fallback_used"] = False
            return payload
        except PerpetualMarketDataError as primary:
            try:
                payload = self._binance_usdm(coins)
                payload["fallback_used"] = True
                payload["primary_error"] = str(primary)
                return payload
            except PerpetualMarketDataError as fallback:
                raise PerpetualMarketDataError(
                    f"hyperliquid={primary};binance={fallback}"
                ) from fallback


__all__ = ["PerpetualPublicMarketData", "PerpetualMarketDataError"]
