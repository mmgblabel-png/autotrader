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

const token = await ethers.deployContract("AIHFAccessToken", [treasury]);
await token.waitForDeployment();

const vault = await ethers.deployContract("AIHFAccessVault", [
  await token.getAddress(),
  ethers.parseEther(reader.toString()),
  ethers.parseEther(pro.toString()),
  ethers.parseEther(quant.toString()),
  cooldown
]);
await vault.waitForDeployment();

console.log(JSON.stringify({
  network: "polygon-amoy",
  token: await token.getAddress(),
  vault: await vault.getAddress(),
  treasury,
  initialSupply: (await token.INITIAL_SUPPLY()).toString(),
  thresholds: { reader: reader.toString(), pro: pro.toString(), quant: quant.toString() },
  unlockCooldownSeconds: cooldown.toString()
}, null, 2));
