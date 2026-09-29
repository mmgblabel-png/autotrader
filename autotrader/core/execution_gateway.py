"""Fail-closed execution policy for paper, shadow and explicitly approved live modes."""
from __future__ import annotations
import os, time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

class ExecutionMode(StrEnum):
    PAPER="paper"; SHADOW="shadow"; LIVE="live"

@dataclass(frozen=True)
class ExecutionLimits:
    max_trade_eur: Decimal=Decimal("10")
    max_daily_exposure_eur: Decimal=Decimal("50")
    max_daily_loss_eur: Decimal=Decimal("25")
    max_slippage_bps: int=50

@dataclass(frozen=True)
class ExecutionRequest:
    venue:str; symbol:str; side:str; notional_eur:Decimal
    expected_price:Decimal; observed_price:Decimal; client_order_id:str; timestamp:float
    risk_reducing: bool=False

@dataclass(frozen=True)
class ExecutionDecision:
    accepted:bool; mode:ExecutionMode; reason:str
    client_order_id:str; venue:str; notional_eur:str

def _bool_env(name:str, default:bool=False)->bool:
    return os.getenv(name,str(default)).strip().lower() in {"1","true","yes","on"}

def _decimal_env(name:str, default:Decimal)->Decimal:
    try:
        v=Decimal(os.getenv(name,str(default)).strip())
        return v if v.is_finite() and v>=0 else default
    except (InvalidOperation,AttributeError):
        return default

def limits_from_environment()->ExecutionLimits:
    try: bps=int(os.getenv("MAX_SLIPPAGE_BPS","50"))
    except ValueError: bps=50
    return ExecutionLimits(
        max_trade_eur=_decimal_env("MAX_TRADE_EUR",Decimal("10")),
        max_daily_exposure_eur=_decimal_env("MAX_DAILY_EXPOSURE_EUR",Decimal("50")),
        max_daily_loss_eur=_decimal_env("MAX_DAILY_LOSS_EUR",Decimal("25")),
        max_slippage_bps=max(0,min(100,bps)),
    )

def live_activation_is_allowed()->bool:
    return (
        os.getenv("EXECUTION_MODE","paper").strip().lower()=="live"
        and _bool_env("LIVE_EXECUTION_APPROVED")
        and _bool_env("LIVE_EXECUTION_ADAPTER_INSTALLED")
        and not _bool_env("EMERGENCY_STOP",True)
        and os.getenv("LIVE_TRADING_CONFIRMATION","")=="I_UNDERSTAND_LIVE_ORDERS"
        and _bool_env("BITVAVO_LIVE_TRADING")
    )

class ExecutionGateway:
    """Central risk gate. Live is possible only when every explicit gate is true."""
    def __init__(self, limits:ExecutionLimits|None=None)->None:
        self.limits=limits or limits_from_environment()
        self.daily_exposure_eur=Decimal("0")
        self.daily_loss_eur=Decimal("0")
        self._seen_order_ids:set[str]=set()

    @property
    def mode(self)->ExecutionMode:
        try: return ExecutionMode(os.getenv("EXECUTION_MODE","paper").strip().lower())
        except ValueError: return ExecutionMode.PAPER

    def reset_daily(self)->None:
        self.daily_exposure_eur=Decimal("0"); self.daily_loss_eur=Decimal("0"); self._seen_order_ids.clear()

    def restore_daily_state(self, *, exposure_eur: Decimal | None = None, loss_eur: Decimal | None = None)->None:
        """Restore durable daily counters after a process restart."""
        if exposure_eur is not None and exposure_eur.is_finite() and exposure_eur >= 0:
            self.daily_exposure_eur = exposure_eur
        if loss_eur is not None and loss_eur.is_finite() and loss_eur >= 0:
            self.daily_loss_eur = loss_eur

    def evaluate(self, request:ExecutionRequest, *, armed: bool = False)->ExecutionDecision:
        now=time.time()
        if not request.client_order_id or request.client_order_id in self._seen_order_ids: return self._reject(request,"missing or duplicate client_order_id")
        if request.timestamp>now+5 or now-request.timestamp>30: return self._reject(request,"request timestamp is stale or invalid")
        if request.venue not in {"binance_spot","bitvavo","polymarket"}: return self._reject(request,"venue is not allowlisted")
        if request.side not in {"BUY","SELL"}: return self._reject(request,"side is invalid")
        if request.notional_eur<=0 or request.notional_eur>self.limits.max_trade_eur: return self._reject(request,"per-trade EUR limit exceeded")
        if (not request.risk_reducing) and self.daily_exposure_eur+request.notional_eur>self.limits.max_daily_exposure_eur:
            return self._reject(request,"daily exposure limit exceeded")
        if self.daily_loss_eur>=self.limits.max_daily_loss_eur: return self._reject(request,"daily loss stop is active")
        if request.expected_price<=0 or request.observed_price<=0: return self._reject(request,"price must be positive")
        if request.side=="BUY":
            adverse_move=max(Decimal("0"),request.expected_price-request.observed_price)
        else:
            adverse_move=max(Decimal("0"),request.observed_price-request.expected_price)
        slippage_bps=adverse_move/request.observed_price*10000
        if slippage_bps>self.limits.max_slippage_bps: return self._reject(request,"slippage limit exceeded")
        if self.mode is ExecutionMode.LIVE:
            if not armed:
                return self._reject(request,"live trading is not armed")
            if not live_activation_is_allowed():
                return self._reject(request,"live activation gates are not satisfied")
        self._seen_order_ids.add(request.client_order_id)
        if not request.risk_reducing:
            self.daily_exposure_eur+=request.notional_eur
        return ExecutionDecision(True,self.mode,"validated for execution" if self.mode is ExecutionMode.LIVE else "validated without sending an order",request.client_order_id,request.venue,str(request.notional_eur))

    def record_loss(self,amount_eur:Decimal)->None:
        if amount_eur>0: self.daily_loss_eur+=amount_eur

    def _reject(self,request:ExecutionRequest,reason:str)->ExecutionDecision:
        return ExecutionDecision(False,self.mode,reason,request.client_order_id,request.venue,str(request.notional_eur))

    def status(self)->dict:
        return {
            "mode":self.mode.value,
            "live_activation_allowed":live_activation_is_allowed(),
            "live_execution_capability":"bitvavo" if live_activation_is_allowed() else "gated",
            "daily_exposure_eur":str(self.daily_exposure_eur),
            "daily_loss_eur":str(self.daily_loss_eur),
            "limits":{"max_trade_eur":str(self.limits.max_trade_eur),"max_daily_exposure_eur":str(self.limits.max_daily_exposure_eur),"max_daily_loss_eur":str(self.limits.max_daily_loss_eur),"max_slippage_bps":self.limits.max_slippage_bps},
        }
