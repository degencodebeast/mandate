import { createX402App } from "./app.js";
import { loadServiceConfig } from "./config.js";
import { FailureSimulator } from "./failure.js";

const isServiceA = process.env.SERVICE_NAME === "search-a";

const config = loadServiceConfig(process.env, {
  serviceName: isServiceA ? "search-a" : "search-b",
  port: 3000,
  failureRate: isServiceA ? 1 : 0,
});

const failureSimulator = isServiceA
  ? new FailureSimulator(config.failureRate, config.failureMode)
  : null;

export default createX402App(config, failureSimulator);
