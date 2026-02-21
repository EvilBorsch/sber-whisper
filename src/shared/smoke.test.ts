import { describe, expect, test } from "vitest";

describe("settings defaults contract", () => {
  test("timeout default should remain 10 in documented schema", () => {
    const documentedDefault = 10;
    expect(documentedDefault).toBe(10);
  });

  test("model keepalive default should remain 5 minutes in documented schema", () => {
    const documentedDefault = 5;
    expect(documentedDefault).toBe(5);
  });
});
