import { readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import request from "supertest";
import { describe, expect, it } from "vitest";

import app from "../src/index.js";

describe("Vercel entry", () => {
  it("exposes only one reserved Vercel server entry", async () => {
    const sourceDirectory = fileURLToPath(new URL("../src", import.meta.url));
    const reservedEntries = (await readdir(sourceDirectory))
      .filter((file) => /^(app|index|server)\.(js|mjs|ts)$/.test(file))
      .sort();

    expect(reservedEntries).toEqual(["index.ts"]);
  });

  it("exports a working Express application", async () => {
    const response = await request(app).get("/health");

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ ok: true, service: "search-b" });
  });
});
