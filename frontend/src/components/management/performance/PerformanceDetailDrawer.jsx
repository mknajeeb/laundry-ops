import {
  Box,
  Drawer,
  IconButton,
  Stack,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";

/**
 * Performance detail surface: bottom sheet on phone, right drawer on tablet/desktop.
 */
export default function PerformanceDetailDrawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = 440,
}) {
  const isPhone = useMediaQuery("(max-width:767px)");

  return (
    <Drawer
      anchor={isPhone ? "bottom" : "right"}
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: isPhone ? "100%" : maxWidth,
          maxWidth: "100%",
          bgcolor: VEEWASH_DASHBOARD.pageBackground,
          ...(isPhone
            ? {
                maxHeight: "92vh",
                borderTopLeftRadius: 16,
                borderTopRightRadius: 16,
              }
            : {}),
        },
      }}
    >
      <Stack
        direction="row"
        alignItems="flex-start"
        justifyContent="space-between"
        spacing={1}
        sx={{
          px: { xs: 1.5, sm: 2 },
          py: 1.25,
          borderBottom: "1px solid #e8eef2",
          bgcolor: "#fff",
          flexShrink: 0,
        }}
      >
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography
            sx={{
              fontWeight: 800,
              fontSize: { xs: 17, sm: 18 },
              lineHeight: 1.2,
              color: "#0f172a",
            }}
          >
            {title}
          </Typography>
          {subtitle ? (
            <Typography sx={{ mt: 0.35, fontSize: 12, color: "#64748b", fontWeight: 600 }}>
              {subtitle}
            </Typography>
          ) : null}
        </Box>
        <IconButton
          size="small"
          onClick={onClose}
          aria-label="Close"
          sx={{ mt: -0.25, color: "#64748b" }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </Stack>

      <Box
        sx={{
          flex: 1,
          overflow: "auto",
          px: { xs: 1.5, sm: 2 },
          py: 1.25,
          WebkitOverflowScrolling: "touch",
        }}
      >
        {children}
      </Box>

      {footer ? (
        <Box
          sx={{
            px: { xs: 1.5, sm: 2 },
            py: 1.25,
            borderTop: "1px solid #e8eef2",
            bgcolor: "#fff",
            flexShrink: 0,
          }}
        >
          {footer}
        </Box>
      ) : null}
    </Drawer>
  );
}

export function PerformanceDetailRow({ primary, secondary, meta, onClick }) {
  const inner = (
    <>
      <Typography sx={{ fontWeight: 700, fontSize: 14, color: "#0f172a", lineHeight: 1.3 }}>
        {primary}
      </Typography>
      {secondary ? (
        <Typography sx={{ mt: 0.2, fontSize: 13, color: "#475569", fontWeight: 600 }}>
          {secondary}
        </Typography>
      ) : null}
      {meta ? (
        <Typography sx={{ mt: 0.15, fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>
          {meta}
        </Typography>
      ) : null}
    </>
  );

  if (!onClick) {
    return (
      <Box sx={{ py: 1.1, borderBottom: "1px solid #f1f5f9" }}>
        {inner}
      </Box>
    );
  }

  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        display: "block",
        width: "100%",
        m: 0,
        py: 1.1,
        px: 0,
        textAlign: "left",
        border: "none",
        borderBottom: "1px solid #f1f5f9",
        bgcolor: "transparent",
        cursor: "pointer",
        fontFamily: "inherit",
        WebkitTapHighlightColor: "transparent",
        "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueLight },
      }}
    >
      {inner}
    </Box>
  );
}

export function PerformanceFilterChip({ active, onClick, children }) {
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        flex: "0 0 auto",
        appearance: "none",
        border: "none",
        borderRadius: 999,
        px: 1.15,
        py: 0.55,
        fontSize: 12,
        fontWeight: 700,
        cursor: "pointer",
        fontFamily: "inherit",
        bgcolor: active ? VEEWASH_DASHBOARD.primaryBlue : "#eef4f6",
        color: active ? "#fff" : "#334155",
        boxShadow: active ? "0 1px 2px rgba(0, 60, 80, 0.12)" : "none",
        transition: "background-color 0.15s ease",
      }}
    >
      {children}
    </Box>
  );
}

export function PerformanceSortSelect({ value, options, onChange, "aria-label": ariaLabel }) {
  return (
    <Box
      component="select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel || "Sort"}
      sx={{
        appearance: "none",
        border: "1px solid #e2e8f0",
        borderRadius: 999,
        px: 1.1,
        py: 0.45,
        fontSize: 12,
        fontWeight: 700,
        color: "#475569",
        bgcolor: "#fff",
        cursor: "pointer",
        fontFamily: "inherit",
        minWidth: 0,
        maxWidth: 140,
      }}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </Box>
  );
}
