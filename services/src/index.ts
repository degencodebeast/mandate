import express from "express";

import { configureX402App } from "./x402-app.js";
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

const app = express();
configureX402App(app, config, failureSimulator);

export default app;
