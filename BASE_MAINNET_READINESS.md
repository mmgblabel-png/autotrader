# Base Mainnet Readiness Assessment and Non-Custodial Execution Design

**Status:** Architecture only. The deployed AutoTrader remains paper-only and must not create, approve, sign, or send Mainnet transactions.

## Readiness assessment

The current product is not a Mainnet trading system. The wallet module is explicitly a stub, while the exchange connectors return placeholder prices, balances, and order responses. The Railway service runs paper strategies and the Hostinger dashboard displays paper data. Therefore, simply changing a wallet network to Base Mainnet would not create a genuine or safe trading capability.

| Capability | Current state | Mainnet requirement |
|---|---|---|
| Wallet custody | Stub only; no real provider integration | MetaMask browser provider only; no server-side private keys, seed phrases, or recovery phrases |
| Network | Paper mode; user previously selected Base Sepolia for readiness | Base Mainnet must be verified as chain ID `8453` before a proposal is shown [1] |
| Market data | Placeholder / simulation | Independent, timestamped, validated quote source with stale-quote rejection |
| Execution | No DEX implementation; exchange methods are stubs | Specific DEX router, immutable allowlist, ABI selector allowlist, simulation, and user-approved MetaMask request |
| Risk controls | Paper loss limits only | Transaction notional caps, aggregate daily caps, slippage caps, gas caps, cooldowns, nonce/replay protection, and emergency disable |
| Monitoring | Paper runtime health | Proposal log, user-confirmed transaction hash, receipt status, rejection/error handling, and alerting |

## Required Mainnet configuration

Base Mainnet uses chain ID **8453**, native currency **ETH**, RPC endpoint `https://mainnet.base.org`, and explorer `https://basescan.org`. The Base documentation warns that the public RPC is rate-limited and unsuitable for production use; a production system must use an independent node provider with a restricted server-side API key.[1]

> The wallet connection remains non-custodial: MetaMask provides the browser provider, while every Mainnet transaction is created only after the user explicitly reviews and approves it in MetaMask. MetaMask’s provider API exposes the account and chain, and its transaction API requires a user-facing transaction request; it does not require a private key to be copied into the application.[2] [3]

## Transaction lifecycle

| Stage | Backend responsibility | Browser / MetaMask responsibility | Hard stop |
|---|---|---|---|
| **1. Connect** | Create a session linked to public address and chain only. Never persist a wallet secret. | User explicitly connects the selected wallet account. | Reject if chain is not Base Mainnet (`8453`). |
| **2. Intent** | Accept only an allowlisted pair, side, and bounded amount. Generate idempotency key. | User enters or confirms a proposed trade intent. | Reject unknown asset, zero/oversized amount, or rate-limit breach. |
| **3. Quote and simulation** | Obtain a quote, verify token decimals and route, simulate calldata, calculate fee/gas bound, enforce short expiry. | Display all amounts and recipient/router before wallet invocation. | Reject stale quote, failed simulation, excessive slippage, unknown target, or expired proposal. |
| **4. Approval policy** | Prefer exact approvals. Never construct unlimited approval. | MetaMask displays any token approval as a distinct transaction; user must approve it separately. | Reject approval above exact required amount or to unallowlisted spender. |
| **5. Swap request** | Return an immutable, signed-by-server *proposal record*, not a wallet signature. | User explicitly triggers `eth_sendTransaction` and reviews the final calldata, amount, gas, and network in MetaMask. | Do not request a signature automatically, in background, or after a route changes. |
| **6. Reconciliation** | Track only public transaction hash and receipt, update audit log, and lock duplicate intent. | User sees pending, confirmed, failed, or rejected state. | Never infer success without an on-chain receipt. |

## Minimum preconditions before implementation

The following inputs are required before the DEX-specific implementation can be built. They are intentionally not guessed because they decide what contracts, quotes, permissions, and risk controls the code must permit.

| Required decision | Why it is required |
|---|---|
| **DEX / routing provider** | Determines the router contract, ABI, quote API, simulation model, and security allowlist. |
| **Asset pairs** | Determines exact token contract addresses and decimal handling. User-entered contract addresses must not be accepted blindly. |
| **Execution policy** | Specifies manual one-click proposals versus unattended execution; MetaMask can only support user-approved signing. |
| **Maximum trade notional** | Becomes a server-enforced per-transaction cap. |
| **Maximum daily loss / aggregate exposure** | Becomes the emergency stop and daily cap. |
| **Maximum slippage and gas budget** | Prevents broad execution beyond reviewed bounds. |
| **Quote provider and RPC provider** | Avoids relying on rate-limited public RPC infrastructure for production. |

## Explicitly excluded from the current product

This work does not create a guarantee of profit, a price prediction engine, an unattended MetaMask trading bot, a server-held wallet, or a Mainnet transaction. The existing `AUTOTRADER_CONTROL_TOKEN` may control paper strategies only; it must never be repurposed to authorize financial transactions.

## References

[1]: https://docs.base.org/base-chain/quickstart/connecting-to-base "Base: Connecting to Base"
[2]: https://docs.metamask.io/wallet/reference/provider-api/ "MetaMask Ethereum Provider API"
[3]: https://docs.metamask.io/wallet/how-to/send-transactions/ "MetaMask: Send Transactions"

## Selected conservative technical baseline

The implementation baseline is a **fail-closed, single-route policy**: Base Mainnet only (`8453`), native Circle-issued Base USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`), Base WETH (`0x4200000000000000000000000000000000000006`), and Uniswap v3 `SwapRouter02` (`0x2626664c2603336E57B271c5C0b26F421741e481`). These addresses are sourced from the official Circle USDC address list and Uniswap Base deployment list.[1] [4]

The policy starts with a **zero notional cap**, which makes every Mainnet proposal fail closed until a user deliberately supplies an amount cap and separately confirms a specific action. It does not use Universal Router or Permit2 in the initial readiness layer: although Universal Router aggregates several protocols and supports signature-controlled Permit2 approvals, that command-and-signature complexity is unnecessary for a narrow, audit-friendly first implementation.[5]

[4]: https://developers.circle.com/stablecoins/usdc-contract-addresses "Circle: USDC contract addresses"
[5]: https://developers.uniswap.org/docs/protocols/v3/deployments/v3-base-deployments "Uniswap v3: Base deployments"
[6]: https://developers.uniswap.org/docs/protocols/universal-router/overview "Uniswap: Universal Router Overview"
