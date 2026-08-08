import "dotenv/config";
import { loadServiceConfig } from "./config.js";
import { createX402App } from "./app.js";
import { FailureSimulator } from "./failure.js";

/**
 * Service A: flaky. It fails a configurable share of paid requests with a 500
 * or a timeout. Default failure rate is 3/5 (0.6) for the demo.
 */
const config = loadServiceConfig(process.env, {
  serviceName: "search-a",
  port: 4021,
  failureRate: 0.6,
});

const failureSimulator = new FailureSimulator(
  config.failureRate,
  config.failureMode,
);

const app = createX402App(config, failureSimulator);

app.listen(config.port, () => {
  console.log(
    `[${config.serviceName}] listening on http://localhost:${config.port} ` +
      `(failure rate ${config.failureRate}, mode ${config.failureMode})`,
  );
});
