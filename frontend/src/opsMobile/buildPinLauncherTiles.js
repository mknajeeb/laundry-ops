/**
 * Build PIN Menu launcher tiles from hub features + attendance snapshot.
 * Presentation only — does not invent permissions or punch rules.
 *
 * Break is intentionally omitted: the PIN attendance PWA has no break
 * start/end action (break lives on authenticated Time Clock only).
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
  checklist: {
    label: "Tasks",
    color: "#0f766e",
    iconKey: "tasks",
  },
  inventory: {
    label: "Stock",
    color: "#0e7490",
    iconKey: "stock",
  },
};

export const CLOCK_DISABLED_HELPER = "Use the shared attendance tablet.";

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
 * @param {Record<string, { allowed?: boolean, label?: string }>|null} opts.features
 * @param {string[]|null} opts.featureOrder
 * @param {{
 *   shared_device_enabled?: boolean,
 *   allow_clock_from_hub?: boolean,
 *   clocked_in?: boolean|null,
 *   on_break?: boolean
 * }|null} opts.attendance
 * @returns {Array<{
 *   id: string,
 *   label: string,
 *   color: string,
 *   iconKey: string,
 *   href?: string,
 *   disabled?: boolean,
 *   disabledHelper?: string
 * }>}
 */
export function buildPinLauncherTiles({ features = {}, featureOrder = null, attendance = null } = {}) {
  const feats = features && typeof features === "object" ? features : {};
  const att = attendance && typeof attendance === "object" ? attendance : {};

  const tiles = [];

  // Clock is always visible on the PIN hub; allow_clock_from_hub controls interactivity only.
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

  const order =
    Array.isArray(featureOrder) && featureOrder.length
      ? featureOrder
      : ["switch_role", "checklist", "inventory"];

  for (const id of order) {
    if (id === "clock" || id === "break") continue;
    const feat = feats[id];
    if (!feat?.allowed) continue;

    // Role only when confirmed clocked in (API rejects otherwise).
    if (id === "switch_role" && att.clocked_in !== true) {
      continue;
    }

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
    if (feat.disabled) {
      tile.disabled = true;
      tile.disabledHelper = feat.disabled_helper || feat.disabledHelper || "";
    }
    tiles.push(tile);
  }

  return tiles;
}
