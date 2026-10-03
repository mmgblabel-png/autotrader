# MMinc AI HedgeFund HQ — Game Maker blueprint

This is the build specification for the one-LAND Sandbox Experience on LAND **(92,115)** / Polygon LAND token **#130448**.

The blueprint deliberately separates **public gameplay**, **native Sandbox NFT-gated presentation spaces**, and **sensitive AIHF web entitlements**.

## Build strategy

Use a strong sci-fi / corporate / vault template as the shell if it materially reduces build time. Strip unrelated story, branding, NPCs and gates before layering the AIHF experience. The template is a production accelerator, not the product identity.

Use one-LAND scale as the hard footprint. Keep performance headroom; do not fill the full vertical volume merely because it is available.

## Player journey

Target first session: **5–8 minutes**.

```
Spawn
  |
  v
Public Plaza
  |
  v
AIHF Lobby ----> Treasury / Tokenomics Gallery
  |
  +----> Risk & Capital Separation Quest
  |
  +----> Research Lift ---- Reader Floor
  |                         |
  |                         +--> Shadow Agent Room
  |
  +----> Pro Lift --------- Pro Strategy Lab
  |
  +----> Quant Lift ------- Quant Vault
  |
  +----> Founder Door ----- Founder Room
  |
  +----> Portal Hall ------ External wallet/dashboard/research portal
```

The public educational quest must remain completable without buying AIHF or an NFT.

## Suggested local footprint

Treat the LAND as a local **96 x 96** design grid.

### Ground / Y 0–12

- **South 0–16:** arrival plaza, spawn, branding, public safety/wallet education.
- **South-middle 16–38:** main public lobby and tier explanation.
- **West 38–70:** treasury/tokenomics gallery.
- **East 38–70:** quest/risk gallery and AutoTrader-capital-separation exhibit.
- **North 70–96:** portal hall, lifts and visible vault facade.

The player should be able to understand what AIHF is within 30 seconds of spawning.

### Research Floor / Y 14–24

Reader presentation layer:
- research exhibit wall;
- delayed/non-sensitive market visualisations;
- historical methodology;
- Shadow Agent/performance room;
- return portal.

Sandbox gate target: **AIHF Reader Access Pass**.

### Pro Strategy Lab / Y 26–36

Pro presentation layer:
- strategy lifecycle exhibits;
- execution-cost/fee lab;
- analytics displays;
- external premium dashboard portal;
- educational build-a-strategy interaction.

Sandbox gate target: **AIHF Pro Access Pass**.

### Quant Vault / Y 38–50

Quant presentation layer:
- advanced simulation methodology;
- API/data architecture;
- marketplace creator workflow;
- research-priority signaling station;
- security boundary displays.

Sandbox gate target: **AIHF Quant Access Pass**.

Sensitive data/API authorization stays outside The Sandbox and re-checks `AIHFAccessVault.tierOf(wallet)`.

### Founder Room / side tower

A visually distinct side room/tower reached from the public lobby.

Gate target: **MMinc Founder Key**.

Perks:
- founder lore;
- founder wall / recognition;
- cosmetic display;
- beta history;
- special non-financial quest;
- private event staging.

Founder Key does not unlock Pro/Quant data or AutoTrader execution.

## Native Sandbox gates

When real assets exist:

1. create Reader / Pro / Quant Sandbox Pass assets in VoxEdit/Workspaces;
2. mint only a minimal closed-beta quantity using Catalysts;
3. store the canonical Sandbox asset URL in `config/sandbox-hq-access.json`;
4. configure Game Maker NFT Sensor against the actual asset URL;
5. validate each gate with an entitled and non-entitled wallet;
6. validate transfer/stale-pass behavior;
7. leave sensitive external portal access behind a fresh wallet-authenticated live vault check.

Do not assume an arbitrary external ERC-721/1155 is recognized as a native Game Maker NFT-gating asset.

## Public onboarding quest

Working name: **Enter the AI HedgeFund HQ**.

Objectives:
1. visit the AIHF identity wall;
2. inspect fixed-supply and no-profit-share statement;
3. learn Reader / Pro / Quant access thresholds;
4. inspect the capital-separation exhibit;
5. find the Shadow Agent transparency display;
6. visit the Portal Hall;
7. complete with a non-financial badge/acknowledgement.

No token purchase is required for completion.

## Monetisation placement

Keep monetisation visible but not intrusive.

- Lobby: explain service subscriptions and AIHF lock utility.
- Founder display: Founder Key showcase and scarcity rules.
- Gallery: cosmetic/collectible drops only when relevant.
- Event wall: clearly labeled sponsored educational events.
- Portal Hall: research/dashboard/strategy marketplace services.
- Never sell combat/stat advantages.
- Never describe AIHF as an investment, dividend or AutoTrader profit claim.

## Art direction

Use the existing **MMinc Founder Key** concept as the visual anchor:
- matte black;
- metallic gold;
- cyan energy;
- dark research-lab architecture;
- large readable voxel signage;
- glowing vertical light paths that visually map Reader -> Pro -> Quant.

Public space should feel accessible; premium rooms should feel progressively more technical rather than simply more luxurious.

## Build milestones

### M0 — shell
- choose/import template;
- remove irrelevant content;
- verify one-LAND bounds and performance;
- establish spawn and vertical circulation.

### M1 — public experience
- lobby;
- treasury gallery;
- separation/risk exhibit;
- public quest;
- portal hall placeholders.

### M2 — premium room shells
- Reader;
- Pro;
- Quant;
- Shadow Agent;
- Founder Room.

### M3 — web bridge
- public AIHF portal;
- MetaMask sign-in;
- live Amoy vault entitlement;
- fail-closed external premium access.

### M4 — native Sandbox beta gates
- create Pass assets;
- configure NFT Sensors;
- minimal Catalyst spend;
- transfer/stale-pass testing.

### M5 — Founder Key beta
- finalize metadata and supply policy;
- mint minimal closed-beta batch;
- Founder Room sensor;
- non-financial perk tests.

### M6 — closed beta acceptance
- public user can finish onboarding with no token;
- Reader, Pro, Quant gates match live entitlement;
- stale/transferred pass cannot leak sensitive web content;
- Founder Key cannot bypass tier authorization;
- no AutoTrader trading wallet/capital is touched;
- no pay-to-win mechanic exists.

## Current dependency

The LAND is already visible in the owner's Polygon wallet/OpenSea, while The Sandbox inventory indexer was still showing zero LANDs in the last check. Continue building the Experience independently, but do not move/bridge the LAND merely to force website indexing. Publish/attach only after The Sandbox ownership index is corrected.
