import { useMemo } from "react";
import PinIssuesFlow from "../opsMobile/PinIssuesFlow";

const PHOTO =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#12324d"/><rect x="70" y="60" width="500" height="300" rx="24" fill="#e8eef5"/><text x="90" y="230" font-size="42" font-family="sans-serif" fill="#12324d">Washer 4</text></svg>`,
  );

const PREVIEW = {
  summary: { total: 3, open: 1, review: 1, resolved: 1 },
  rows: [
    {
      key: "employee:42",
      source: "employee",
      source_id: 42,
      category: "equipment",
      category_label: "Equipment Not Working",
      status: "new",
      status_group: "open",
      employee_name: "Ana Rivera",
      reported_at: "2026-11-21 14:05:00",
      business_date: "2026-11-21",
      location: "Washer 4",
      order_reference: "",
      summary: "Washer stops mid-cycle and will not restart.",
      photo_count: 1,
    },
    {
      key: "employee:41",
      source: "employee",
      source_id: 41,
      category: "orphan",
      category_label: "Found Item",
      status: "under_review",
      status_group: "review",
      employee_name: "Luis Ortega",
      reported_at: "2026-11-21 11:20:00",
      location: "Folding table 2",
      order_reference: "",
      summary: "Blue shirt with no ticket.",
      photo_count: 1,
    },
    {
      key: "rinse:18",
      source: "rinse",
      source_id: 18,
      category: "MISSING",
      category_label: "Missing / Bag",
      status: "resolved",
      status_group: "resolved",
      employee_name: "Sam Patel",
      reported_at: "2026-11-20 16:40:00",
      order_reference: "A347CPMO70",
      customer_name: "North",
      summary: "Bag missing at checkout.",
      photo_count: 0,
    },
  ],
  details: {
    "employee:42": {
      source: "employee",
      row: {
        key: "employee:42",
        source: "employee",
        source_id: 42,
        category: "equipment",
        category_label: "Equipment Not Working",
      },
      item: {
        id: 42,
        report_category: "equipment",
        status: "new",
        employee_name: "Ana Rivera",
        reported_at_display: "2026-11-21 14:05:00",
        location_label: "Washer 4",
        notes: "Washer stops mid-cycle and will not restart.",
        status_comment: "",
        photos: [{ id: 7, url: PHOTO }],
      },
      events: [
        {
          id: 1,
          event_type: "reported",
          actor_name: "Ana Rivera",
          created_at_display: "2026-11-21 14:05:00",
        },
      ],
    },
  },
};

export default function DevPinIssuesPreviewPage() {
  const preview = useMemo(() => PREVIEW, []);
  return <PinIssuesFlow preview={preview} onBack={() => {}} onLock={() => {}} />;
}
