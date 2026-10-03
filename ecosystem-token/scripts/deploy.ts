import { network } from "hardhat";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

function positiveInteger(name: string, fallback: string): bigint {
  const raw = process.env[name]?.trim() || fallback;
  const value = BigInt(raw);
  if (value <= 0n) throw new Error(`${name} must be positive`);
  return value;
}

const { ethers } = await network.create();
const chain = await ethers.provider.getNetwork();
if (chain.chainId !== 80002n) {
  throw new Error(`Refusing deployment: expected Polygon Amoy chainId 80002, got ${chain.chainId}`);
}

const [deployer] = await ethers.getSigners();
const deployerAddress = await deployer.getAddress();
const treasury = required("AIHF_TREASURY_ADDRESS");

if (!ethers.isAddress(treasury) || treasury === ethers.ZeroAddress) {
  throw new Error("AIHF_TREASURY_ADDRESS must be a non-zero EVM address");
}

const reader = positiveInteger("AIHF_READER_THRESHOLD", "100");
const pro = positiveInteger("AIHF_PRO_THRESHOLD", "1000");
const quant = positiveInteger("AIHF_QUANT_THRESHOLD", "10000");
const cooldown = positiveInteger("AIHF_UNLOCK_COOLDOWN_SECONDS", "604800");

if (!(reader < pro && pro < quant)) {
  throw new Error("Access thresholds must satisfy READER < PRO < QUANT");
}
if (cooldown < 86400n || cooldown > 30n * 86400n) {
  throw new Error("AIHF_UNLOCK_COOLDOWN_SECONDS must be between 1 and 30 days");
}

const deployerBalanceBefore = await ethers.provider.getBalance(deployerAddress);
if (deployerBalanceBefore === 0n) {
  throw new Error("Amoy deployer has no test POL for gas");
}

const token = await ethers.deployContract("AIHFAccessToken", [treasury]);
await token.waitForDeployment();

const tokenAddress = await token.getAddress();
const vault = await ethers.deployContract("AIHFAccessVault", [
  tokenAddress,
  ethers.parseEther(reader.toString()),
  ethers.parseEther(pro.toString()),
  ethers.parseEther(quant.toString()),
  cooldown
]);
await vault.waitForDeployment();

const vaultAddress = await vault.getAddress();
const expectedSupply = await token.INITIAL_SUPPLY();
const totalSupply = await token.totalSupply();
const treasuryBalance = await token.balanceOf(treasury);

if (totalSupply !== expectedSupply || treasuryBalance !== expectedSupply) {
  throw new Error("Post-deployment supply invariant failed");
}
if ((await vault.token()).toLowerCase() !== tokenAddress.toLowerCase()) {
  throw new Error("Vault token-address invariant failed");
}
if ((await vault.readerThreshold()) !== ethers.parseEther(reader.toString())) {
  throw new Error("Reader threshold invariant failed");
}
if ((await vault.proThreshold()) !== ethers.parseEther(pro.toString())) {
  throw new Error("Pro threshold invariant failed");
}
if ((await vault.quantThreshold()) !== ethers.parseEther(quant.toString())) {
  throw new Error("Quant threshold invariant failed");
}
if ((await vault.unlockCooldown()) !== cooldown) {
  throw new Error("Unlock cooldown invariant failed");
}

const tokenCode = await ethers.provider.getCode(tokenAddress);
const vaultCode = await ethers.provider.getCode(vaultAddress);
if (tokenCode === "0x" || vaultCode === "0x") {
  throw new Error("Post-deployment bytecode check failed");
}

const latest = await ethers.provider.getBlock("latest");
const deployerBalanceAfter = await ethers.provider.getBalance(deployerAddress);

console.log(JSON.stringify({
  schemaVersion: 1,
  environment: "testnet",
  network: "polygon-amoy",
  chainId: Number(chain.chainId),
  blockNumber: latest?.number ?? null,
  token: tokenAddress,
  vault: vaultAddress,
  treasury,
  deployer: deployerAddress,
  initialSupply: expectedSupply.toString(),
  totalSupply: totalSupply.toString(),
  treasuryBalance: treasuryBalance.toString(),
  thresholds: {
    reader: reader.toString(),
    pro: pro.toString(),
    quant: quant.toString()
  },
  unlockCooldownSeconds: cooldown.toString(),
  tokenRuntimeCodeHash: ethers.keccak256(tokenCode),
  vaultRuntimeCodeHash: ethers.keccak256(vaultCode),
  deployerTestPolSpentWei: (deployerBalanceBefore - deployerBalanceAfter).toString(),
  verifiedInvariants: [
    "chain_is_polygon_amoy",
    "fixed_supply_matches_initial_supply",
    "entire_initial_supply_at_configured_test_treasury",
    "vault_points_to_token",
    "tier_thresholds_match",
    "unlock_cooldown_matches",
    "runtime_bytecode_present"
  ]
}, null, 2));
