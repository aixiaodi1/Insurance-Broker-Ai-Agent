import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("session menu styles", () => {
  it("keeps the session list scrollable while rendering the action menu as a floating layer", () => {
    const css = readFileSync(join(process.cwd(), "app", "globals.css"), "utf8");
    const sessionListRule = css.match(/\.session-list\s*\{[^}]*\}/)?.[0] ?? "";
    const sessionMenuRule = css.match(/\.session-menu\s*\{[^}]*\}/)?.[0] ?? "";

    expect(sessionListRule).toMatch(/overflow-y:\s*auto/);
    expect(sessionListRule).toMatch(/overflow-x:\s*hidden/);
    expect(sessionMenuRule).toMatch(/position:\s*fixed/);
  });
});
