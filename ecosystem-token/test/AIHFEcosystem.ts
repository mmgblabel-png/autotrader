import { expect } from "chai";
import { network } from "hardhat";

describe("AIHF ecosystem contracts", function () {
  async function deployFixture() {
    const { ethers, networkHelpers } = await network.create();
    const [treasury, user, relayer] = await ethers.getSigners();

    const token = await ethers.deployContract("AIHFAccessToken", [treasury.address]);
    await token.waitForDeployment();

    const reader = ethers.parseEther("100");
    const pro = ethers.parseEther("1000");
    const quant = ethers.parseEther("10000");
    const cooldown = 7 * 24 * 60 * 60;

    const vault = await ethers.deployContract("AIHFAccessVault", [
      await token.getAddress(), reader, pro, quant, cooldown
    ]);
    await vault.waitForDeployment();

    return { ethers, networkHelpers, treasury, user, relayer, token, vault, reader, pro, quant, cooldown };
  }

  it("mints the complete fixed supply once to treasury", async function () {
    const { token, treasury } = await deployFixture();
    const supply = await token.INITIAL_SUPPLY();

    expect(await token.totalSupply()).to.equal(supply);
    expect(await token.balanceOf(treasury.address)).to.equal(supply);
    expect(supply).to.equal(100_000_000n * 10n ** 18n);
  });

  it("has no privileged mint, upgrade, or blacklist entry point", async function () {
    const { token } = await deployFixture();

    expect(token.interface.hasFunction("mint(address,uint256)")).to.equal(false);
    expect(token.interface.hasFunction("upgradeToAndCall(address,bytes)")).to.equal(false);
    expect(token.interface.hasFunction("blacklist(address)")).to.equal(false);
  });

  it("grants access strictly from actively locked tokens", async function () {
    const { token, vault, treasury, user, reader, pro } = await deployFixture();

    await token.connect(treasury).transfer(user.address, pro);
    await token.connect(user).approve(await vault.getAddress(), pro);

    await expect(vault.connect(user).lock(reader))
      .to.emit(vault, "Locked")
      .withArgs(user.address, reader, reader);

    expect(await vault.tierOf(user.address)).to.equal(1n);

    await vault.connect(user).lock(pro - reader);
    expect(await vault.tierOf(user.address)).to.equal(2n);
    expect(await vault.totalLocked()).to.equal(pro);
    expect(await token.balanceOf(await vault.getAddress())).to.equal(pro);
  });

  it("removes a pending unlock from access immediately and enforces cooldown", async function () {
    const { token, vault, treasury, user, pro, reader, cooldown, networkHelpers } = await deployFixture();

    await token.connect(treasury).transfer(user.address, pro);
    await token.connect(user).approve(await vault.getAddress(), pro);
    await vault.connect(user).lock(pro);

    await vault.connect(user).requestUnlock(pro - reader + 1n);
    expect(await vault.tierOf(user.address)).to.equal(0n);

    await expect(vault.connect(user).executeUnlock())
      .to.be.revertedWithCustomError(vault, "UnlockCooldownActive");

    await networkHelpers.time.increase(cooldown);
    await vault.connect(user).executeUnlock();

    expect(await vault.lockedBalance(user.address)).to.equal(reader - 1n);
    expect(await vault.tierOf(user.address)).to.equal(0n);
  });

  it("lets the user cancel an unlock and restores access without moving tokens", async function () {
    const { token, vault, treasury, user, pro } = await deployFixture();

    await token.connect(treasury).transfer(user.address, pro);
    await token.connect(user).approve(await vault.getAddress(), pro);
    await vault.connect(user).lock(pro);

    await vault.connect(user).requestUnlock(pro);
    expect(await vault.tierOf(user.address)).to.equal(0n);

    await vault.connect(user).cancelUnlock();
    expect(await vault.tierOf(user.address)).to.equal(2n);
    expect(await vault.lockedBalance(user.address)).to.equal(pro);
  });

  it("remains usable when a valid permit is frontrun by a relayer", async function () {
    const { ethers, token, vault, treasury, user, relayer, reader } = await deployFixture();

    await token.connect(treasury).transfer(user.address, reader);

    const tokenAddress = await token.getAddress();
    const vaultAddress = await vault.getAddress();
    const chain = await ethers.provider.getNetwork();
    const nonce = await token.nonces(user.address);
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 3600);

    const signature = ethers.Signature.from(await user.signTypedData(
      {
        name: "AI HedgeFund Access Token",
        version: "1",
        chainId: chain.chainId,
        verifyingContract: tokenAddress
      },
      {
        Permit: [
          { name: "owner", type: "address" },
          { name: "spender", type: "address" },
          { name: "value", type: "uint256" },
          { name: "nonce", type: "uint256" },
          { name: "deadline", type: "uint256" }
        ]
      },
      {
        owner: user.address,
        spender: vaultAddress,
        value: reader,
        nonce,
        deadline
      }
    ));

    // Anyone may submit a permit. Simulate a relayer consuming it first.
    await token.connect(relayer).permit(
      user.address,
      vaultAddress,
      reader,
      deadline,
      signature.v,
      signature.r,
      signature.s
    );

    // The vault catches the now-stale permit and uses the allowance safely.
    await vault.connect(user).lockWithPermit(
      reader,
      deadline,
      signature.v,
      signature.r,
      signature.s
    );

    expect(await vault.activeLockedBalance(user.address)).to.equal(reader);
    expect(await vault.tierOf(user.address)).to.equal(1n);
  });

  it("enforces a four-year team schedule with a one-year cliff", async function () {
    const { ethers, networkHelpers, token, treasury, user } = await deployFixture();
    const DAY = 24 * 60 * 60;
    const latest = await ethers.provider.getBlock("latest");
    if (!latest) throw new Error("latest block unavailable");

    const start = latest.timestamp;
    const duration = 4 * 365 * DAY;
    const cliff = 365 * DAY;
    const allocation = ethers.parseEther("15000000");

    const vesting = await ethers.deployContract("AIHFVestingWallet", [
      user.address,
      start,
      duration,
      cliff
    ]);
    await vesting.waitForDeployment();
    await token.connect(treasury).transfer(await vesting.getAddress(), allocation);

    await networkHelpers.time.increase(cliff - 1);
    expect(await vesting.releasable(await token.getAddress())).to.equal(0n);

    await networkHelpers.time.increase(1);
    const cliffReleasable = await vesting.releasable(await token.getAddress());
    expect(cliffReleasable).to.be.greaterThanOrEqual(allocation / 4n);

    await vesting.connect(user).release(await token.getAddress());
    expect(await token.balanceOf(user.address)).to.be.greaterThanOrEqual(allocation / 4n);

    await networkHelpers.time.increase(3 * 365 * DAY);
    await vesting.connect(user).release(await token.getAddress());
    expect(await token.balanceOf(user.address)).to.equal(allocation);
  });

  it("rejects over-withdraw requests", async function () {
    const { token, vault, treasury, user, reader } = await deployFixture();

    await token.connect(treasury).transfer(user.address, reader);
    await token.connect(user).approve(await vault.getAddress(), reader);
    await vault.connect(user).lock(reader);

    await expect(vault.connect(user).requestUnlock(reader + 1n))
      .to.be.revertedWithCustomError(vault, "InsufficientLockedBalance");
  });
});
