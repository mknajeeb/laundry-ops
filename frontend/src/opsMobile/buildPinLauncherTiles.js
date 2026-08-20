/**
 * Build PIN Menu launcher tiles from hub features + attendance snapshot.
 * Presentation only — does not invent permissions or punch rules.
 *
 * Break is intentionally omitted: the PIN attendance PWA has no break
 * start/end action (break lives on authenticated Time Clock only).
 *
 * Hang Dry is not a separate hub tile — it lives inside Revenue / Cash.
 * Clock is always last so operational tiles stay compact/mobile-first.
 */

export const PIN_LAUNCHER_META = {
  clock: {
    color: "#2d3d9c",
    iconKey: "clock",
  },
  switch_role: {
    label: "Role",
    color: "#4338ca",
    iconKey: "role",
  },
  revenue_cost: {
    label: "Revenue / Cash",
    color: "#b45309",
    iconKey: "revenue",
  },
  checklist: {
    label: "End-of-Day Checklist",
    color: "#0f766e",
    iconKey: "tasks",
  },
  inventory: {
    label: "Inventory",
    color: "#0e7490",
    iconKey: "stock",
  },
};

/** Preferred PIN Home order; Clock is appended last by buildPinLauncherTiles. */
export const PIN_HOME_FEATURE_ORDER = [
  "switch_role",
  "revenue_cost",
  "checklist",
  "inventory",
];

export const CLOCK_DISABLED_HELPER = "Use the shared attendance tablet.";

export const ROLE_CLOCK_IN_FIRST_MESSAGE =
  "Clock in first using the shared attendance tablet, then return here to change your role.";

export const ROLE_ON_BREAK_MESSAGE =
  "Finish your break before changing role. Use Resume after Break to pick your role.";

/** Clock label from reliable attendance state only. */
export function clockTileLabel(attendance) {
  const att = attendance && typeof attendance === "object" ? attendance : {};
  if (att.clocked_in === true) return "Clock Out";
  if (att.clocked_in === false) return "Clock In";
  return "Clock";
}

/**
 * Whether mobile PIN hub Clock In/Out is interactive.
 * Defaults on when the field is absent (backward compatible).
 */
export function isClockAllowedFromHub(attendance) {
  const att = attendance && typeof attendance === "object" ? attendance : {};
  return att.allow_clock_from_hub !== false;
}

/**
 * @param {object} opts
 * @param {Record<string, { allowed?: boolean, label?: string, requires_clock_in?: boolean }>|null} opts.features
 * @param {string[]|null} opts.featureOrder
 * @param {object|null} opts.attendance
 */
export function buildPinLauncherTiles({ features = {}, featureOrder = null, attendance = null } = {}) {
  const feats = features && typeof features === "object" ? features : {};
  const att = attendance && typeof attendance === "object" ? attendance : {};

  const tiles = [];

  const requested =
    Array.isArray(featureOrder) && featureOrder.length ? featureOrder : PIN_HOME_FEATURE_ORDER;
  const seen = new Set();
  const order = [];
  for (const id of [...PIN_HOME_FEATURE_ORDER, ...requested]) {
    if (!id || seen.has(id) || id === "clock" || id === "break" || id === "hang_dry") continue;
    seen.add(id);
    order.push(id);
  }

  for (const id of order) {
    const feat = feats[id];
    if (!feat?.allowed) continue;

    const meta = PIN_LAUNCHER_META[id] || {
      label: feat.label || id,
      color: "#2d3d9c",
      iconKey: "tasks",
    };
    const tile = {
      id,
      label: meta.label || feat.label || id,
      color: meta.color,
      iconKey: meta.iconKey,
    };
    if (id === "switch_role" && (feat.requires_clock_in || att.clocked_in !== true)) {
      tile.requiresClockIn = true;
    }
    if (id === "switch_role" && (feat.blocked_reason === "on_break" || att.on_break === true)) {
      tile.disabled = true;
      tile.disabledHelper = feat.disabled_helper || ROLE_ON_BREAK_MESSAGE;
      tile.blockedReason = "on_break";
    }
    if (feat.disabled) {
      tile.disabled = true;
      tile.disabledHelper = feat.disabled_helper || feat.disabledHelper || tile.disabledHelper || "";
    }
    tiles.push(tile);
  }

  const clockAllowed = isClockAllowedFromHub(att);
  tiles.push({
    id: "clock",
    label: clockTileLabel(att),
    color: PIN_LAUNCHER_META.clock.color,
    iconKey: PIN_LAUNCHER_META.clock.iconKey,
    href: "attendance",
    disabled: !clockAllowed,
    disabledHelper: clockAllowed ? "" : CLOCK_DISABLED_HELPER,
  });

  return tiles;
}
