import { Box, Button } from "@mui/material";

/**
 * Rush / non-rush style tabs with counts. When count === 0, tab uses green styling.
 * No extra queue copy under the bar (counts live in the tab only).
 */
export default function RushTabCountBar({ value, onChange, tabs, fullWidth = false }) {
  return (
    <Box
      sx={{
        mt: 1,
        display: "grid",
        gridTemplateColumns: fullWidth ? `repeat(${tabs.length}, minmax(0, 1fr))` : "auto auto auto",
        gap: 0.75,
        overflowX: fullWidth ? "visible" : "auto",
        pb: 0.25,
      }}
    >
      {tabs.map(({ key, label, count, Icon, accent }) => {
        const selected = value === key;
        const empty = Number(count || 0) === 0;
        const base = accent || "#0f172a";
        let bg;
        let fg;
        if (empty) {
          bg = selected ? "#15803d" : "#dcfce7";
          fg = selected ? "#ffffff" : "#166534";
        } else if (selected) {
          bg = base;
          fg = "#ffffff";
        } else {
          bg = "#eef2f7";
          fg = "#111827";
        }
        return (
          <Button
            key={key}
            fullWidth={fullWidth}
            onClick={() => onChange(key)}
            sx={{
              textTransform: "none",
              borderRadius: 999,
              px: 1.4,
              py: fullWidth ? 1.1 : 0.75,
              fontWeight: 600,
              minHeight: fullWidth ? 52 : 44,
              bgcolor: bg,
              color: fg,
              border: empty ? "1px solid #86efac" : "1px solid transparent",
              whiteSpace: "nowrap",
            }}
            startIcon={Icon ? <Icon sx={{ fontSize: 20 }} /> : null}
          >
            {label} {count}
          </Button>
        );
      })}
    </Box>
  );
}
