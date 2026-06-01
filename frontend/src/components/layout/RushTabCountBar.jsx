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
        {tabs.map(({ key, label, count, Icon, accent, detail }) => {
          const selected = value === key;
          const empty = Number(count || 0) === 0;
          const base = accent || "#0f172a";
          let bg;
          let fg;
          let border;
          if (empty) {
            bg = selected ? "#475569" : "#f8fafc";
            fg = selected ? "#ffffff" : "#64748b";
            border = selected ? "2px solid #64748b" : "1px solid #e2e8f0";
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
                {tab.detail ? (
                  <Typography sx={{ fontSize: 10, fontWeight: 500, opacity: 0.85, lineHeight: 1.25, px: 0.25 }}>
                    {tab.detail}
                  </Typography>
                ) : null}
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
          bg = selected ? "#475569" : "#f1f5f9";
          fg = selected ? "#ffffff" : "#64748b";
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
              border: empty ? "1px solid #cbd5e1" : "1px solid transparent",
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
