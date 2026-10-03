import { network } from "hardhat";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

const { ethers } = await network.create();
const chain = await ethers.provider.getNetwork();
if (chain.chainId !== 80002n) {
  throw new Error(`Refusing deployment: expected Polygon Amoy chainId 80002, got ${chain.chainId}`);
}

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

const vestingWallet = await vesting.getAddress();
const code = await ethers.provider.getCode(vestingWallet);
if (code === "0x") throw new Error("Vesting wallet runtime bytecode missing");
if ((await vesting.owner()).toLowerCase() !== beneficiary.toLowerCase()) {
  throw new Error("Vesting beneficiary invariant failed");
}
if ((await vesting.start()) !== startTimestamp) {
  throw new Error("Vesting start invariant failed");
}
if ((await vesting.duration()) !== durationSeconds) {
  throw new Error("Vesting duration invariant failed");
}
if ((await vesting.cliff()) !== startTimestamp + cliffSeconds) {
  throw new Error("Vesting cliff invariant failed");
}

console.log(JSON.stringify({
  schemaVersion: 1,
  environment: "testnet",
  network: "polygon-amoy",
  chainId: Number(chain.chainId),
  vestingWallet,
  beneficiary,
  startTimestamp: startTimestamp.toString(),
  durationSeconds: durationSeconds.toString(),
  cliffSeconds: cliffSeconds.toString(),
  cliffTimestamp: (startTimestamp + cliffSeconds).toString(),
  runtimeCodeHash: ethers.keccak256(code),
  verifiedInvariants: [
    "chain_is_polygon_amoy",
    "beneficiary_matches",
    "48_month_schedule",
    "12_month_cliff",
    "runtime_bytecode_present"
  ]
}, null, 2));
