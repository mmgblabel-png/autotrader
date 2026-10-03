import hardhatToolboxMochaEthers from "@nomicfoundation/hardhat-toolbox-mocha-ethers";
import { configVariable, defineConfig } from "hardhat/config";

export default defineConfig({
  plugins: [hardhatToolboxMochaEthers],
  solidity: {
    version: "0.8.28",
    settings: { optimizer: { enabled: true, runs: 500 } }
  },
  networks: {
    amoy: {
      type: "http",
      chainType: "l1",
      chainId: 80002,
      url: configVariable("POLYGON_AMOY_RPC_URL"),
      accounts: [configVariable("DEPLOYER_PRIVATE_KEY")]
    }
  },
  test: { mocha: { timeout: 40_000 } }
});
