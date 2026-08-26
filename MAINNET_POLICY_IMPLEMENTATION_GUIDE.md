# API Compatibility Fix and Fail-Closed Mainnet Policy Implementation

## Exact 404 route fix

The dashboard calls `GET /api/strategies/status`, while the backend originally exposed only `GET /strategies/status`. The compatible server change is an additional decorator on the existing handler, not a duplicate implementation:

```python
@app.get("/strategies/status", tags=["strategies"])
@app.get("/api/strategies/status", tags=["strategies"])
def strategies_status():
    ...
```

Both paths now return the same payload:

```json
{
  "running": {
    "MarketMaker": false,
    "ArbitrageHunter": false,
    "GridRunner": false,
    "SniperBot": false
  }
}
```

## Server-side Railway environment policy

`MainnetExecutionPolicy.from_environment()` reads the following values using strict, fail-closed parsing. Invalid booleans preserve the safe defaults; invalid, negative, or non-finite numerical values become `0`; slippage outside the hard bound `0–100` basis points becomes `0`.

| Variable | Parsed as | Safe default | Enforced by validator |
|---|---|---:|---|
| `MAINNET_EXECUTION_ENABLED` | Boolean | `false` | Reject every proposal when false. |
| `MAINNET_EMERGENCY_STOP` | Boolean | `true` | Reject every proposal when true. |
| `MAINNET_MAX_TRADE_USDC` | Decimal | `0` | Reject any proposal until a positive per-trade cap exists; reject proposals above it. |
| `MAINNET_MAX_DAILY_USDC` | Decimal | `0` | Reject proposals until a positive daily gross-exposure cap exists; reject cap breaches. |
| `MAINNET_MAX_DAILY_LOSS_USDC` | Decimal | `0` | Reject proposals until a positive loss cap exists; stop when reconciled daily loss reaches the cap. |
| `MAINNET_MAX_SLIPPAGE_BPS` | Integer | `0` | Reject any intent whose supplied slippage exceeds the policy cap. |
| `MAINNET_MAX_GAS_ETH` | Decimal | `0` | Reject proposals until a positive fee cap exists; reject estimated-fee breaches. |

The `GET /api/mainnet/safety` endpoint is read-only. It reports non-secret policy values plus `execution_capability: not_implemented`, `wallet_capability: not_implemented`, `approval_capability: not_implemented`, and `broadcast_capability: not_implemented`. It does not create a wallet or transaction path.

## What is enforced now, and what is still required

The policy validator enforces configuration against a supplied proposal and server-reconciled `daily_used_usdc` and `daily_realized_loss_usdc` inputs. The current deployment has no signer, quote provider, ledger, DEX call, approval code, or transaction broadcaster. Therefore it cannot yet reconcile values on chain or submit a swap. This is intentional.

A future execution implementation must persist an immutable proposal, record submitted/pending/confirmed exposure, calculate realized loss plus confirmed fees from a durable ledger, run fresh quote/simulation checks, and pass those server-derived values into `policy.validate()` before a browser-only MetaMask request is offered. Client-provided PnL, exposure, or route data must never be authoritative.

## Exact final pre-signature low-value test gate

This is a future procedure only; it must stop before signing until a separate, exact confirmation exists.

| Step | Required result |
|---|---|
| 1. Freeze policy | Commit a versioned policy with explicit caps and an active audit record. |
| 2. Verify wallet | User verifies public account and Base Mainnet (`8453`) in MetaMask; no secret is shared. |
| 3. Load proposal | Use only the immutable USDC/WETH and router allowlist, a positive but explicitly confirmed input amount, and short quote TTL. |
| 4. Reconcile controls | Server ledger reports current exposure/loss; policy validates daily cap, loss stop, slippage, fee cap, route, and expiry. |
| 5. Simulate | Approved provider simulates the exact route and computes minimum output from the slippage cap. |
| 6. Render review | Show exact input, minimum output, router, approval amount, fee, expiry, and policy version. |
| 7. Confirm | User explicitly confirms that exact transaction in this conversation and then reviews the final request in MetaMask. |
| 8. Submit once | Future browser-only signer submits one transaction; server records public hash and receipt. |

No value is “safe” by itself. A low notional limits potential size but does not guarantee that a route, approval, gas cost, price, or transaction result is safe or profitable.
