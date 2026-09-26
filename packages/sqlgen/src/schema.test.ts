import { describe, expect, it } from "vitest";
import { goldenCases } from "./fixtures.ts";
import { buildUserPrompt, ident, serializeSchema } from "./schema.ts";

describe("golden fixtures", () => {
  const cases = goldenCases();

  it("has at least 5 fixtures", () => {
    expect(cases.length).toBeGreaterThanOrEqual(5);
  });

  it.each(cases)("$name matches byte-for-byte", (c) => {
    expect(buildUserPrompt(serializeSchema(c.schema), c.question)).toBe(
      c.expected,
    );
  });
});

describe("ident", () => {
  it("quotes only when needed", () => {
    expect(ident("singer_id")).toBe("singer_id");
    expect(ident("Order")).toBe('"Order"');
    expect(ident("a b")).toBe('"a b"');
    expect(ident('x"y')).toBe('"x""y"');
  });
});
