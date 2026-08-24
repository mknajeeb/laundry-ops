/**
 * Authenticated production Capacity Planner simulate verification.
 * Usage: CAPACITY_PLANNER_TEST_USER=... CAPACITY_PLANNER_TEST_PASSWORD=... node scripts/verify_capacity_planner_production.mjs
 */
const API_BASE =
  process.env.CAPACITY_PLANNER_API_BASE
  || "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";
const USER = process.env.CAPACITY_PLANNER_TEST_USER || "";
const PASS = process.env.CAPACITY_PLANNER_TEST_PASSWORD || "";
const ORG = process.env.CAPACITY_PLANNER_ORG_SLUG || "veewash";

const payload = {
  engine: "bag_des_v2",
  management_mode: true,
  start_time: "5:00 AM",
  target_time: "4:00 PM",
  end_time: "4:00 PM",
  planning_block_size_min: 60,
  summary_interval_min: 60,
  bag_count: 180,
  avg_lbs_per_bag: 20,
  two_washer_split_pct: 50,
  two_dryer_split_pct: 25,
  washer_count: 28,
  dryer_count: 28,
  batch_size: 8,
  weigh_sec_per_bag: 45,
  sort_min_per_bag: 5,
  load_washer_min: 2,
  wash_cycle_min: 23,
  load_dryer_min: 3,
  dry_cycle_min: 40,
  fold_min_per_bag: 6,
  fold_rate_mode: "minutes_per_bag",
  staffing_plan: {
    intervals: [
      { role: "weigher", people: 2, start: "5:00 AM", end: "4:00 PM", mode: "base" },
      { role: "sorter", people: 2, start: "5:00 AM", end: "4:00 PM", mode: "base" },
      { role: "washer", people: 4, start: "5:00 AM", end: "4:00 PM", mode: "base" },
      { role: "dryer", people: 4, start: "5:00 AM", end: "4:00 PM", mode: "base" },
      { role: "folder", people: 4, start: "5:00 AM", end: "4:00 PM", mode: "base" },
    ],
  },
  _skip_recommendations: true,
};

async function main() {
  const health = await fetch(`${API_BASE}/health`);
  const healthJson = await health.json();
  console.log("PRODUCTION_REVISION:", healthJson.artifact_revision || healthJson.git_sha);

  if (!USER || !PASS) {
    console.error("Set CAPACITY_PLANNER_TEST_USER and CAPACITY_PLANNER_TEST_PASSWORD for authenticated simulate.");
    process.exit(2);
  }

  const loginStart = Date.now();
  const loginRes = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: USER,
      password: PASS,
      organization_slug: ORG,
    }),
  });
  const loginJson = await loginRes.json();
  if (!loginRes.ok) {
    console.error("LOGIN_FAILED:", loginJson?.error || loginRes.status);
    process.exit(1);
  }
  const token = loginJson.token || loginJson.access_token;
  if (!token) {
    console.error("LOGIN_NO_TOKEN");
    process.exit(1);
  }
  console.log("LOGIN_MS:", Date.now() - loginStart);

  const body = JSON.stringify(payload);
  console.log("REQUEST_BYTES:", Buffer.byteLength(body));

  const simStart = Date.now();
  const simStartIso = new Date(simStart).toISOString();
  const simRes = await fetch(`${API_BASE}/rinse/shift-analysis/shift-capacity-planner/simulate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body,
  });
  const simEnd = Date.now();
  const simEndIso = new Date(simEnd).toISOString();
  const text = await simRes.text();
  console.log("REQUEST_START:", simStartIso);
  console.log("REQUEST_END:", simEndIso);
  console.log("CLIENT_DURATION_MS:", simEnd - simStart);
  console.log("HTTP_STATUS:", simRes.status);
  console.log("RESPONSE_BYTES:", Buffer.byteLength(text));
  console.log("TIMEOUT_30S:", simEnd - simStart > 30000 ? "YES" : "NO");

  if (!simRes.ok) {
    console.error("SIMULATE_FAILED:", text.slice(0, 500));
    process.exit(1);
  }

  const data = JSON.parse(text);
  console.log("SIMULATION_VALID:", data.simulation_valid);
  console.log("BAG_ROWS:", (data.bag_rows || data.bags || []).length);
  console.log("ENGINE:", data.engine);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
