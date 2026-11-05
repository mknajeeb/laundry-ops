import { groupOperations, operationsBucket, operationsBucketLabel } from "./operationsGrouping";

describe("operations grouping", () => {
  it("groups a week by Eastern business date and keeps Monday as the week start", () => {
    const rows = [
      { business_date: "2026-11-05", role: "later" },
      { business_date: "2026-11-04", role: "earlier" },
      { business_date: "2026-11-03", role: "tuesday" },
    ];
    const daily = groupOperations(rows, "daily");
    expect(daily.map((bucket) => bucket.key)).toEqual(["2026-11-03", "2026-11-04", "2026-11-05"]);
    expect(daily[0].rows[0].role).toBe("tuesday");
    expect(operationsBucket("2026-11-05", "weekly").start).toBe("2026-11-02");
    expect(operationsBucket("2026-11-01", "weekly").start).toBe("2026-10-26");
    expect(operationsBucket("2026-11-05", "monthly").key).toBe("2026-11");
    expect(operationsBucketLabel(operationsBucket("2026-11-05", "daily"))).toBe("Nov 5, 2026");
  });
});
