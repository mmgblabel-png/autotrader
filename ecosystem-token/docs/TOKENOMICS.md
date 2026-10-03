# Tokenomics policy

## Fixed supply

**100,000,000 AIHF**. The token contract has no mint function after construction.

All supply is initially minted to the launch treasury. On mainnet that treasury must be a Safe multisig and distribution must follow the published allocation schedule.

## Target allocation

| Allocation | Share | Tokens | Mainnet release principle |
| --- | ---: | ---: | --- |
| Ecosystem access & user programs | 35% | 35,000,000 | multi-year, service-linked distribution; no promised yield |
| Product & treasury reserve | 25% | 25,000,000 | Safe multisig; disclosed operating budget |
| Team & long-term contributors | 15% | 15,000,000 | minimum 12-month cliff, then 36-month linear vesting |
| Research grants & integrations | 10% | 10,000,000 | milestone-based grants, transparent recipients |
| Liquidity reserve | 10% | 10,000,000 | not deployed before legal/audit/liquidity-policy gate |
| Security, audit & contingency reserve | 5% | 5,000,000 | security/audit/ecosystem incidents; disclosed use |

Total: 100%.

## Economic design constraints

- No APY, staking yield or guaranteed return.
- No dividend or revenue share.
- No token-holder claim on AutoTrader assets, treasury cash, investment profits or liquidation value.
- No automatic buyback promise.
- No algorithmic price peg or stable-value claim.
- No transfer tax, reflection fee, anti-sell mechanism or hidden fee.
- No leverage or borrowing against the AutoTrader fund.
- Treasury AIHF is never counted as AutoTrader NAV.

## Access mechanics

Tokens locked in the access vault remain associated with the user's address but cannot be transferred while locked. The vault pays no yield.

Default engineering tiers are 100 / 1,000 / 10,000 AIHF for Reader / Pro / Quant. These thresholds are deployment parameters, not price targets. Mainnet thresholds must be chosen from actual service design and legal review, not a desired token valuation.

## Liquidity principles

Public DEX liquidity is a separate post-compliance phase. The project must not advertise liquidity, listing or future price as guaranteed. Any treasury-supplied liquidity must have a published wallet, budget, risk policy and conflict-of-interest disclosure.
