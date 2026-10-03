import { network } from "hardhat";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

const { ethers } = await network.create();
const beneficiary = required("AIHF_TEAM_BENEFICIARY");

if (!ethers.isAddress(beneficiary) || beneficiary === ethers.ZeroAddress) {
  throw new Error("AIHF_TEAM_BENEFICIARY must be a non-zero EVM address");
}

const latest = await ethers.provider.getBlock("latest");
if (!latest) throw new Error("Unable to read latest block");

const DAY = 24 * 60 * 60;
const startTimestamp = BigInt(latest.timestamp);
const durationSeconds = BigInt(4 * 365 * DAY);
const cliffSeconds = BigInt(365 * DAY);

const vesting = await ethers.deployContract("AIHFVestingWallet", [
  beneficiary,
  startTimestamp,
  durationSeconds,
  cliffSeconds
]);
await vesting.waitForDeployment();

console.log(JSON.stringify({
  network: "polygon-amoy",
  vestingWallet: await vesting.getAddress(),
  beneficiary,
  startTimestamp: startTimestamp.toString(),
  durationSeconds: durationSeconds.toString(),
  cliffSeconds: cliffSeconds.toString()
}, null, 2));
