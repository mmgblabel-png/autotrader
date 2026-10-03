# AIHF -> Sandbox Access Bridge

## Why a hybrid bridge is required

AIHF remains an ERC-20 utility token. The Sandbox Game Maker NFT Sensor is designed around NFT ownership, including specific Sandbox NFTs and supported collections. Therefore the canonical AIHF entitlement should **not** be replaced by a transferable NFT.

The bridge has two layers:

1. **Canonical entitlement** — live `AIHFAccessVault.tierOf(wallet)` on Polygon.
2. **Sandbox presentation pass** — a Sandbox-native Pass asset used only for in-world gating/perks.

The canonical entitlement always wins.

## Native Sandbox constraint

For native NFT Sensor gating, use Pass assets created in VoxEdit / Sandbox Workspaces and minted through The Sandbox flow. Do not deploy an arbitrary external ERC-721/ERC-1155 and assume Game Maker's NFT Sensor will treat it as a supported native gating asset.

The project may display compatible external Polygon NFT imagery, but display compatibility is not the same as entitlement-gating support.

## Testnet-first bridge flow

### Phase A — no NFT minting

On Polygon Amoy:

1. user connects wallet to AIHF web app;
2. user signs a one-time domain-bound login challenge;
3. backend reads the canonical Amoy vault;
4. backend returns Reader / Pro / Quant entitlement;
5. Sandbox HQ runs with public rooms and mocked/test-only gate markers;
6. no real Catalyst spend is required.

### Phase B — Sandbox pass beta

When the Sandbox asset workflow is ready:

1. create three Sandbox Pass assets:
   - AIHF Reader Access Pass;
   - AIHF Pro Access Pass;
   - AIHF Quant Access Pass;
2. upload to Workspaces;
3. mint only the smallest beta quantity required;
4. record each canonical Sandbox Asset URL in `config/sandbox-hq-access.json`;
5. configure NFT Sensor rules from those URLs;
6. issue passes only to wallets that passed the live AIHF entitlement check.

Because Sandbox passes may remain transferable and native NFT Sensor does not provide a cryptographic revocation link to AIHF locks, passes are treated as **bounded-lived presentation credentials**, never as authority for sensitive research/API data.

## Epoch policy

Default beta policy:
- one entitlement epoch is at most **30 days**;
- the web entitlement revokes/downgrades immediately when the vault tier falls;
- in-world pass-only perks can remain until the current epoch ends;
- a new pass for the next epoch is issued only after a fresh live entitlement check.

For shorter beta windows, reduce the epoch to 7 days.

## Tier changes

Upgrade:
- live web tier changes as soon as the canonical vault state is safe/finalized;
- the next eligible Sandbox pass can be issued.

Unlock request / downgrade:
- the vault's active balance falls immediately by design;
- web premium access downgrades immediately;
- existing Sandbox pass may continue only for non-sensitive in-world perks until epoch expiry.

## Founder Key

The **MMinc Founder Key** is independent from AIHF lock tiers.

It may gate:
- Founder Room;
- founder lore;
- cosmetics;
- beta invitations;
- community recognition.

It must not:
- grant Pro/Quant web research without the matching live vault entitlement;
- create profit-sharing rights;
- create rights to AutoTrader NAV;
- alter AutoTrader risk or strategy;
- provide a pay-to-win advantage.

## Bridge service API

Recommended endpoints:

- `POST /api/ecosystem/auth/nonce`
- `POST /api/ecosystem/auth/verify`
- `GET /api/ecosystem/access`
- `GET /api/ecosystem/sandbox/pass-eligibility`
- `POST /api/ecosystem/sandbox/pass-claim`
- `GET /api/ecosystem/sandbox/pass-status`

`pass-claim` must be idempotent per wallet, tier and epoch.

## Security requirements

- never request or store user seed phrases/private keys;
- bridge issuer key is separate from AutoTrader, AIHF treasury and deployer keys;
- issuer can issue only pre-approved Sandbox pass assets;
- enforce chain ID and canonical vault address;
- use a single-use signed login nonce;
- rate-limit claims;
- store claim audit records;
- verify finality before issuing;
- fail closed on RPC/indexer disagreement;
- never let a Sandbox pass authorize AutoTrader execution;
- never use AutoTrader trading capital for Catalyst purchases or bridge operations.

## Operational fallback

If native Sandbox pass automation cannot be made reliable, keep the LAND open and move premium authorization to the external AIHF portal. The in-world rooms remain educational/showcase spaces. This is safer than pretending a transferable pass is equivalent to a live vault entitlement.
