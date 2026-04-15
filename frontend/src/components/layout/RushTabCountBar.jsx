import { Box, Button, Paper, Stack, Typography } from "@mui/material";

/**
 * Rush / non-rush style tabs with counts. When count === 0, tab uses green styling.
 * `variant="cards"`: touch cards in a row (floor ops).
 */
export default function RushTabCountBar({ value, onChange, tabs, fullWidth = false, variant = "pills" }) {
  if (variant === "cards") {
    return (
      <Box
        sx={{
          mt: 1,
          display: "grid",
          gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))`,
          gap: 1,
          pb: 0.25,
        }}
      >
        {tabs.map(({ key, label, count, Icon, accent }) => {
          const selected = value === key;
          const empty = Number(count || 0) === 0;
          const base = accent || "#0f172a";
          let bg;
          let fg;
          let border;
          if (empty) {
            bg = selected ? "#15803d" : "#f0fdf4";
            fg = selected ? "#ffffff" : "#166534";
            border = selected ? "2px solid #22c55e" : "1px solid #bbf7d0";
          } else if (selected) {
            bg = base;
            fg = "#ffffff";
            border = `2px solid ${base}`;
          } else {
            bg = "#ffffff";
            fg = "#111827";
            border = "1px solid #e2e8f0";
          }
          return (
            <Paper
              key={key}
              elevation={0}
              onClick={() => onChange(key)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onChange(key);
                }
              }}
              sx={{
                borderRadius: 2,
                p: 1.15,
                cursor: "pointer",
                bgcolor: bg,
                color: fg,
                border,
                boxShadow: selected ? "0 6px 18px rgba(15,23,42,0.12)" : "0 1px 4px rgba(15,23,42,0.06)",
                outline: "none",
                "&:focus-visible": { boxShadow: "0 0 0 3px rgba(59,130,246,0.45)" },
              }}
            >
              <Stack spacing={0.6} alignItems="center" textAlign="center">
                <Box
                  sx={{
                    height: 28,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {Icon ? <Icon sx={{ fontSize: 26 }} /> : null}
                </Box>
                <Typography sx={{ fontWeight: 800, fontSize: "1.05rem", letterSpacing: 0.02 }}>
                  {label}
                </Typography>
                <Typography sx={{ fontSize: 13, fontWeight: 600, opacity: 0.92 }}>{count}</Typography>
              </Stack>
            </Paper>
          );
        })}
      </Box>
    );
  }

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
