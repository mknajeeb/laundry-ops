import { Box, Typography } from "@mui/material";

const SECTIONS = [
  { id: "overview", label: "Today", short: "•" },
  { id: "self_service", label: "Self Service", short: "SS" },
  { id: "drop_off", label: "Drop Off", short: "Drop" },
  { id: "rinse_wf", label: "Rinse WF", short: "WF" },
  { id: "rinse_hd", label: "Rinse HD", short: "HD" },
  { id: "dhs", label: "DHS", short: "DHS" },
  { id: "cash", label: "Cash", short: "Cash" },
];

/**
 * Mobile-first horizontal segmented nav — scrollable, large tap targets, strong active state.
 */
export default function RevenueSectionNav({ value, onChange }) {
  return (
    <Box
      sx={{
        display: "flex",
        gap: 0.75,
        overflowX: "auto",
        WebkitOverflowScrolling: "touch",
        pb: 0.5,
        mx: -0.5,
        px: 0.5,
        scrollbarWidth: "none",
        "&::-webkit-scrollbar": { display: "none" },
      }}
    >
      {SECTIONS.map((s) => {
        const active = value === s.id;
        return (
          <Box
            key={s.id}
            component="button"
            type="button"
            onClick={() => onChange(s.id)}
            sx={{
              flex: "0 0 auto",
              appearance: "none",
              border: 0,
              cursor: "pointer",
              fontFamily: "inherit",
              minHeight: 40,
              px: 1.5,
              borderRadius: 999,
              bgcolor: active ? "#007a91" : "rgba(0,122,145,0.08)",
              color: active ? "#fff" : "#0f172a",
              fontWeight: 800,
              fontSize: 13,
              letterSpacing: 0.1,
              whiteSpace: "nowrap",
              boxShadow: active ? "0 4px 12px rgba(0,122,145,0.28)" : "none",
            }}
          >
            <Typography component="span" sx={{ fontSize: { xs: 13, sm: 14 }, fontWeight: 800, color: "inherit" }}>
              {s.label}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}

export { SECTIONS };
