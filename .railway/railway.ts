import {
  defineRailway,
  github,
  preserve,
  project,
  service,
  volume,
} from "railway/iac";

export default defineRailway(() => {
  const data = volume("campaign-data", {
    region: "europe-west4",
    sizeMB: 512,
  });

  const api = service("campaign-automaton", {
    source: github("mmgblabel-png/autotrader", { branch: "main" }),
    start: "./scripts/start.sh",
    healthcheck: "/api/health",
    healthcheckTimeout: 120,
    replicas: 1,
    volumeMounts: {
      "/data": data,
    },
    env: {
      APP_ENV: "production",
      DATA_DIR: "/data",
      DATABASE_PATH: "/data/campaign_automaton.db",
      CAMPAIGN_CONFIG_PATH: "/app/config/campaign.yaml",
      PAYPRO_PRODUCT_URL:
        "https://www.paypro.nl/producten/WegMetDieKilos_Bronze_Plan/114766/183297",
      DRAFT_ONLY: "true",
      HEARTBEAT_ENABLED: "true",
      AUTO_RUN_DUE_CAMPAIGNS: "false",
      DAILY_TIKTOK_REVIEW_ENABLED: "true",
      DAILY_TIKTOK_REVIEW_CAMPAIGNS: "freds-bouwtekeningen,communicatie-canvas",
      PUBLIC_BASE_URL: preserve(),
      PAYPRO_AFFILIATE_ID: preserve(),
      PAYPRO_AFFILIATE_URL_TEMPLATE: preserve(),
      CONTROL_TOKEN: preserve(),
      WEBHOOK_TOKEN: preserve(),
      OPENAI_API_KEY: preserve(),
      OPENAI_BASE_URL: preserve(),
    },
  });

  return project("paypromoney", {
    resources: [api, data],
  });
});
