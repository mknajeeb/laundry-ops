/**
 * Catch components that call useAuth() without importing it.
 * (Production regression: FinalizeBatchNavigator import replaced the useAuth import.)
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SRC = join(HERE, "..");

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (
      /\.(jsx?|tsx?)$/.test(name) &&
      !name.includes(".test.") &&
      !name.includes(".nodetest.")
    ) {
      out.push(p);
    }
  }
  return out;
}

function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("useAuth import contract", () => {
  it("every file that calls useAuth() imports it from AuthContext", () => {
    const offenders = [];
    for (const file of walk(SRC)) {
      if (file.endsWith("AuthContext.jsx")) continue;
      const raw = readFileSync(file, "utf8");
      const text = stripComments(raw);
      if (!/\buseAuth\s*\(/.test(text)) continue;
      const importsUseAuth = /import\s*\{[^}]*\buseAuth\b[^}]*\}\s*from\s*["'][^"']*AuthContext["']/.test(
        raw,
      );
      if (!importsUseAuth) {
        offenders.push(relative(SRC, file));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("PayoutDetailsPanel imports useAuth (known production failure mode)", () => {
    const raw = readFileSync(join(SRC, "components/PayoutDetailsPanel.jsx"), "utf8");
    expect(raw).toMatch(
      /import\s*\{\s*useAuth\s*\}\s*from\s*["']\.\.\/context\/AuthContext["']/,
    );
    expect(raw).toMatch(/\buseAuth\s*\(/);
  });
});
