import { Box, Typography } from "@mui/material";
import OpsLauncherTile from "./OpsLauncherTile";

export const PIN_MENU_SECTIONS = [
  { id: "management", labelKey: "mobileOps.section.management", fallback: "Management" },
  { id: "work", labelKey: "mobileOps.section.work", fallback: "Floor" },
  { id: "attendance", labelKey: "mobileOps.section.attendance", fallback: "Attendance" },
];

/**
 * Launcher grid stays two columns at 320px so the PIN menu fits the viewport.
 * Tiles remain at least the shared touch minimum and wrap Spanish labels.
 */
export default function OpsLauncherGrid({ tiles = [], busyId = "", disabled = false, onSelect }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 1,
        width: "100%",
      }}
    >
      {tiles.map((tile) => {
        const tileDisabled = disabled || !!tile.disabled;
        return (
          <OpsLauncherTile
            key={tile.id}
            label={tile.label}
            helper={tile.helper || ""}
            icon={tile.icon}
            color={tile.color}
            busy={busyId === tile.id}
            disabled={tileDisabled}
            badge={tile.badge || 0}
            disabledHelper={tile.disabledHelper || ""}
            onClick={() => {
              if (tile.disabled) return;
              onSelect?.(tile);
            }}
            aria-label={tile.ariaLabel || tile.label}
          />
        );
      })}
    </Box>
  );
}

export function OpsLauncherSections({ tiles = [], t = null, ...gridProps }) {
  const groups = PIN_MENU_SECTIONS.map((section) => ({
    ...section,
    tiles: tiles.filter((tile) => (tile.group || "work") === section.id),
  })).filter((section) => section.tiles.length > 0);
  const showHeadings = groups.length > 1;
  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 1.75, width: "100%" }}>
      {groups.map((section) => (
        <Box key={section.id}>
          {showHeadings ? (
            <Typography
              variant="overline"
              sx={{ display: "block", mb: 0.75, letterSpacing: "0.08em", fontWeight: 800, color: "#64748b" }}
            >
              {typeof t === "function" ? t(section.labelKey) : section.fallback}
            </Typography>
          ) : null}
          <OpsLauncherGrid tiles={section.tiles} {...gridProps} />
        </Box>
      ))}
    </Box>
  );
}
