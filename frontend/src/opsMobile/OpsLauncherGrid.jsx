import { Box } from "@mui/material";
import OpsLauncherTile from "./OpsLauncherTile";
import { OPS_MOBILE } from "./tokens";

/**
 * Launcher grid: two equal columns by default; one column under 360px
 * so labels and 56px+ targets stay comfortable (no text squeeze).
 */
export default function OpsLauncherGrid({ tiles = [], busyId = "", disabled = false, onSelect }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        [`@media (max-width: ${OPS_MOBILE.launcherSingleColMax}px)`]: {
          gridTemplateColumns: "1fr",
        },
        gap: 1.25,
        width: "100%",
      }}
    >
      {tiles.map((tile) => (
        <OpsLauncherTile
          key={tile.id}
          label={tile.label}
          icon={tile.icon}
          color={tile.color}
          busy={busyId === tile.id}
          disabled={disabled}
          onClick={() => onSelect?.(tile)}
          aria-label={tile.ariaLabel || tile.label}
        />
      ))}
    </Box>
  );
}
