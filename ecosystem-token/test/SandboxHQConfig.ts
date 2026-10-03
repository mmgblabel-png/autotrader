import { expect } from "chai";
import { readFile } from "node:fs/promises";

describe("Sandbox Monetized Empire configuration", function () {
  async function loadJson(path: string) {
    return JSON.parse(await readFile(new URL(path, import.meta.url), "utf8"));
  }

  it("keeps Sandbox access thresholds aligned with the canonical AIHF catalog", async function () {
    const catalog = await loadJson("../config/access-catalog.json");
    const sandbox = await loadJson("../config/sandbox-hq-access.json");

    for (const tier of ["READER", "PRO", "QUANT"]) {
      expect(sandbox.tiers[tier].minimum_locked_aihf)
        .to.equal(catalog.tiers[tier].minimum_locked_aihf);
    }
  });

  it("keeps sensitive portals behind a live AIHF entitlement check", async function () {
    const sandbox = await loadJson("../config/sandbox-hq-access.json");

    for (const portal of sandbox.external_portals) {
      expect(portal.requires_wallet_signature).to.equal(true);
      expect(portal.requires_live_entitlement).to.equal(true);
    }
  });

  it("does not allow Founder Key to bypass premium entitlement or trading boundaries", async function () {
    const sandbox = await loadJson("../config/sandbox-hq-access.json");
    const denied = new Set(sandbox.founder_key.does_not_grant);

    expect(denied.has("pro_research_without_pro_entitlement")).to.equal(true);
    expect(denied.has("quant_research_without_quant_entitlement")).to.equal(true);
    expect(denied.has("autotrader_profit_share")).to.equal(true);
    expect(denied.has("autotrader_nav_claim")).to.equal(true);
    expect(denied.has("trading_advantage")).to.equal(true);
  });

  it("hard-disables AutoTrader live capital and pay-to-win economics", async function () {
    const sandbox = await loadJson("../config/sandbox-hq-access.json");

    expect(sandbox.economics.autotrader_live_capital_allowed).to.equal(false);
    expect(sandbox.economics.pay_to_win).to.equal(false);
    expect(sandbox.economics.profit_share).to.equal(false);
    expect(sandbox.economics.nav_claim).to.equal(false);
  });

  it("records the owned LAND identity without embedding a wallet secret", async function () {
    const sandbox = await loadJson("../config/sandbox-hq-access.json");

    expect(sandbox.experience.land.coordinates).to.deep.equal([92, 115]);
    expect(sandbox.experience.land.token_id).to.equal("130448");
    expect(JSON.stringify(sandbox)).not.to.match(/private[_ -]?key|seed phrase/i);
  });
});
