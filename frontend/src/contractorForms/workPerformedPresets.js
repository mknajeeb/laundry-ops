/** Preset contractor service descriptions (service-based language only). */

export const WORK_PERFORMED_PRESETS = [
  {
    id: "laundry_processing",
    label: "Laundry processing support",
    description:
      "Laundry processing support, including sorting, washing, drying, transferring, folding, weighing, bagging, and related customer-order handling.",
  },
  {
    id: "folding_bagging",
    label: "Folding and bagging support",
    description:
      "Folding and bagging support for customer laundry orders.",
  },
  {
    id: "wash_dry_transfer",
    label: "Wash / dry / transfer support",
    description:
      "Washing, drying, sorting, loading, unloading, and washer-to-dryer transfer support.",
  },
  {
    id: "pickup_delivery",
    label: "Pickup and delivery support",
    description:
      "Pickup and delivery support for customer laundry orders, including bag handling, loading/unloading, and route-related service support.",
  },
  {
    id: "cleaning_premises",
    label: "Cleaning and premises support",
    description:
      "Cleaning and premises support, including floor cleanup, machine-area cleanup, trash removal, and related facility support.",
  },
  {
    id: "maintenance_repair",
    label: "Maintenance / repair support",
    description:
      "Maintenance or repair support for laundry equipment, fixtures, premises, or related systems.",
  },
  {
    id: "other",
    label: "Other",
    description: "",
  },
];

export function presetById(id) {
  return WORK_PERFORMED_PRESETS.find((p) => p.id === id) || null;
}

/** Combined text for DB / print when only one field is stored. */
export function formatWorkPerformedForSave(record) {
  const main = String(record?.work_performed || "").trim();
  const notes = String(record?.work_performed_notes || "").trim();
  if (!notes) return main;
  if (!main) return notes;
  return `${main}\n\nAdditional notes: ${notes}`;
}

/** Split stored work_performed back into main + notes (best effort). */
export function parseWorkPerformedStored(stored) {
  const raw = String(stored || "").trim();
  if (!raw) {
    return { work_performed_preset: "", work_performed: "", work_performed_notes: "" };
  }
  const split = raw.split(/\n\nAdditional notes:\s*/i);
  if (split.length > 1) {
    const main = split[0].trim();
    const preset = WORK_PERFORMED_PRESETS.find((p) => p.description === main);
    return {
      work_performed_preset: preset?.id || "other",
      work_performed: main,
      work_performed_notes: split.slice(1).join("\n\nAdditional notes: ").trim(),
    };
  }
  const preset = WORK_PERFORMED_PRESETS.find((p) => p.description === raw);
  return {
    work_performed_preset: preset?.id || (raw ? "other" : ""),
    work_performed: raw,
    work_performed_notes: "",
  };
}
