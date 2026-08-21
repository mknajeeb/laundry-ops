/**
 * Build PIN Menu launcher tiles from hub features + attendance snapshot.
 * Presentation only — does not invent permissions or punch rules.
 *
 * Take a Break / Resume Work are attendance tiles driven by hub snapshot
 * (clocked in / on break). Change Role is hidden while on break.
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
  take_break: {
    label: "Take a Break",
    color: "#0f766e",
    iconKey: "break",
  },
  resume_work: {
    label: "Resume Work",
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
  team_status: {
    label: "Team Status",
    color: "#1d4ed8",
    iconKey: "team",
  },
};

/** Preferred PIN Home order; Clock is appended last by buildPinLauncherTiles. */
export const PIN_HOME_FEATURE_ORDER = [
  "resume_work",
  "switch_role",
  "take_break",
  "team_status",
  "revenue_cost",
  "checklist",
  "inventory",
];

export const CLOCK_DISABLED_HELPER = "Use the shared attendance tablet.";

export const ROLE_CLOCK_IN_FIRST_MESSAGE =
  "Clock in first using the shared attendance tablet, then return here to change your role.";

export const ROLE_ON_BREAK_MESSAGE =
  "Finish your break before changing role. Use Resume Work to pick your role.";

export const PIN_LAUNCHER_I18N = {
  switch_role: "mobileOps.tile.role",
  take_break: "mobileOps.tile.takeBreak",
  resume_work: "mobileOps.tile.resumeWork",
  team_status: "mobileOps.tile.teamStatus",
  revenue_cost: "mobileOps.tile.revenueCash",
  checklist: "mobileOps.tile.checklist",
  inventory: "mobileOps.tile.inventory",
};

export const PIN_LAUNCHER_HELPER_I18N = {
  team_status: "mobileOps.tile.teamStatusHelper",
  take_break: "mobileOps.tile.takeBreakHelper",
  resume_work: "mobileOps.tile.resumeWorkHelper",
};

export function clockTileLabel(attendance, t = null) {
  const att = attendance && typeof attendance === "object" ? attendance : {};
  if (att.clocked_in === true) return t ? t("mobileOps.tile.clockOut") : "Clock Out";
  if (att.clocked_in === false) return t ? t("mobileOps.tile.clockIn") : "Clock In";
  return t ? t("mobileOps.tile.clock") : "Clock";
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
 * @param {(key: string) => string} [opts.t] optional translator
 */
export function buildPinLauncherTiles({
  features = {},
  featureOrder = null,
  attendance = null,
  t = null,
} = {}) {
  const feats = features && typeof features === "object" ? features : {};
  const att = attendance && typeof attendance === "object" ? attendance : {};
  const tr = typeof t === "function" ? t : null;

  const tiles = [];

  const requested =
    Array.isArray(featureOrder) && featureOrder.length ? featureOrder : PIN_HOME_FEATURE_ORDER;
  const seen = new Set();
  const order = [];
  for (const id of [...PIN_HOME_FEATURE_ORDER, ...requested]) {
    if (!id || seen.has(id) || id === "clock" || id === "hang_dry") continue;
    seen.add(id);
    order.push(id);
  }

  for (const id of order) {
    const feat = feats[id];
    if (!feat?.allowed || feat?.hidden) continue;

    const meta = PIN_LAUNCHER_META[id] || {
      label: feat.label || id,
      color: "#2d3d9c",
      iconKey: "tasks",
    };
    const i18nKey = PIN_LAUNCHER_I18N[id];
    const helperKey = PIN_LAUNCHER_HELPER_I18N[id];
    const tile = {
      id,
      label: (tr && i18nKey ? tr(i18nKey) : null) || meta.label || feat.label || id,
      color: meta.color,
      iconKey: meta.iconKey,
      helper:
        (tr && helperKey ? tr(helperKey) : null) ||
        (id === "team_status" ? "Who's working today" : "") ||
        "",
    };
    if (id === "switch_role" && (feat.requires_clock_in || att.clocked_in !== true)) {
      tile.requiresClockIn = true;
    }
    if (id === "switch_role" && (feat.blocked_reason === "on_break" || att.on_break === true)) {
      // Should be hidden by backend; keep as safety net.
      continue;
    }
    if (id === "resume_work") {
      tile.resumeFromBreak = true;
    }
    if (feat.disabled) {
      tile.disabled = true;
      tile.disabledHelper = feat.disabled_helper || feat.disabledHelper || tile.disabledHelper || "";
    }
    tiles.push(tile);
  }

  const clockAllowed = isClockAllowedFromHub(att);
  // Break Mode: do not offer Clock Out from the launcher (Resume Work only).
  if (att.on_break !== true) {
    tiles.push({
      id: "clock",
      label: clockTileLabel(att, tr),
      color: PIN_LAUNCHER_META.clock.color,
      iconKey: PIN_LAUNCHER_META.clock.iconKey,
      href: "attendance",
      disabled: !clockAllowed,
      disabledHelper: clockAllowed
        ? ""
        : tr
          ? tr("mobileOps.clockDisabledHelper")
          : CLOCK_DISABLED_HELPER,
    });
  }

  return tiles;
}
