/**
 * Pick washpro | veewash (Mac + Windows). Prints vendor to stdout.
 * Skip prompt: RINSE_VENDOR=washpro|veewash
 */
import readline from "node:readline";

const raw = (process.env.RINSE_VENDOR || "").trim().toLowerCase();
if (raw) {
  if (raw === "washpro" || raw === "1" || raw === "wp") {
    console.log("washpro");
    process.exit(0);
  }
  if (raw === "veewash" || raw === "2" || raw === "vw") {
    console.log("veewash");
    process.exit(0);
  }
  console.error(`Unknown RINSE_VENDOR: ${process.env.RINSE_VENDOR}`);
  process.exit(1);
}

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
console.log("");
console.log("Which Rinse vendor?");
console.log("  1) WashPro");
console.log("  2) VeeWash");
console.log("");
rl.question("Enter 1 or 2: ", (answer) => {
  rl.close();
  const a = String(answer || "").trim().toLowerCase();
  if (a === "1" || a === "washpro") {
    console.log("washpro");
    process.exit(0);
  }
  if (a === "2" || a === "veewash") {
    console.log("veewash");
    process.exit(0);
  }
  console.error("Invalid choice.");
  process.exit(1);
});
