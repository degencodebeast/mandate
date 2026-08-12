import "dotenv/config";
import { loadServiceConfig } from "./config.js";
import { createX402App } from "./x402-app.js";

/**
 * Service B: reliable. Every paid request returns 200 with JSON results.
 */
const config = loadServiceConfig(process.env, {
  serviceName: "search-b",
  port: 4022,
  failureRate: 0,
});

const app = createX402App(config, null);

app.listen(config.port, () => {
  console.log(
    `[${config.serviceName}] listening on http://localhost:${config.port} (reliable)`,
  );
});
