import { Box } from "@mui/material";
import OpsLauncherTile from "./OpsLauncherTile";

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
