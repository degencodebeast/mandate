import request from "supertest";
import { describe, expect, it } from "vitest";

import app from "../src/index.js";

describe("Vercel entry", () => {
  it("exports a working Express application", async () => {
    const response = await request(app).get("/health");

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ ok: true, service: "search-b" });
  });
});
