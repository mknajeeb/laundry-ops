/**
 * One-time (or when cookies expire): open Rinse in a real window, you log in fully
 * (including MFA), then press Enter in this terminal to save cookies to rinse-auth.json.
 *
 *   HEADED=1 node save-session.mjs
 *
 * Then set in .env:  RINSE_STORAGE_STATE=./rinse-auth.json
 * so nightly scrape does not need RINSE_PASSWORD every time (until session expires).
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import readline from "node:readline";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outFile = path.join(__dirname, "rinse-auth.json");

async function main() {
  const browser = await chromium.launch({ headless: false, slowMo: 50 });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("https://www.rinse.com/", { waitUntil: "domcontentloaded" });

  console.log("\n1. Log in to Rinse in the browser window (MFA if needed).");
  console.log("2. Navigate once to Cleaner tickets so you know the session works.");
  console.log("3. Come back here and press Enter to save session →", outFile, "\n");

  await new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question("Press Enter when logged in… ", () => {
      rl.close();
      resolve();
    });
  });

  await context.storageState({ path: outFile });
  await browser.close();
  console.log("Saved. Add to .env: RINSE_STORAGE_STATE=./rinse-auth.json");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
