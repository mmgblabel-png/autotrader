# Product and revenue model

## Product thesis

AIHF exists to unlock **software and data utility**, not to represent an investment in AutoTrader.

The token is an access credential that can be locked to unlock increasingly capable products around market research, strategy analytics and developer tooling. The core product must be useful even if AIHF has no secondary-market price.

## Product surfaces

### Public
- methodology and risk-policy documentation;
- product status and transparency pages;
- delayed educational material.

### Reader
- research feed;
- historical research archive;
- market watchlists;
- portfolio/risk education.

### Pro
- premium dashboard;
- lower-delay research;
- strategy performance analytics;
- alerts;
- downloadable datasets/reports.

### Quant
- real-time research entitlement;
- high-rate data/API access;
- advanced strategy lab;
- marketplace creator tooling;
- non-binding research-signal voting.

The canonical machine-readable entitlement set is in `config/access-catalog.json`.

## Revenue model

The business should monetize **services**, not promises of token appreciation.

Permitted product models for legal review:
1. fiat/stable-value subscription for premium software;
2. AIHF lock as an alternative entitlement path;
3. enterprise/API contracts priced independently of token market value;
4. marketplace service fees on actual software/data transactions, subject to legal/CASP review.

Explicitly excluded:
- promised investment return;
- percentage of AutoTrader profit;
- dividend;
- redemption against fund NAV;
- guaranteed buybacks;
- guaranteed secondary-market liquidity;
- token-price targets.

## Strategy marketplace

The marketplace distributes software licences, research packs, indicators, templates and strategy configurations. It must not automatically grant third parties the ability to place trades from the user's exchange account.

A listing record should contain:
- creator identifier;
- immutable strategy/version hash;
- supported venue/markets;
- methodology summary;
- backtest window and data provenance;
- fee/slippage assumptions;
- live/shadow evidence where available;
- risk characteristics;
- licence terms;
- price and payment method;
- security review state.

Execution-capable code requires a separate sandbox/security approval before it can interact with AutoTrader.

## Research budget signaling

QUANT users may sign non-binding votes on research priorities, for example:
- which markets receive simulation budget;
- which execution topics receive engineering attention;
- which datasets/integrations should be evaluated.

V1 votes do **not** move treasury funds and do not control the company, AutoTrader bankroll or risk mandate. Any future binding financial governance requires a new legal and security review.

## Separation from AutoTrader

AIHF and its treasury are outside the live fund accounting boundary:
- AIHF treasury balance is not NAV;
- AIHF is not collateral;
- AutoTrader never auto-buys AIHF;
- token price never changes strategy sizing;
- token holders have no claim on trading profits;
- launch/liquidity spending cannot come from the live trading bankroll.
