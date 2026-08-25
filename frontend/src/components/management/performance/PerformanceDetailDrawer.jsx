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
import { PERF_TYPE, PERF_UI } from "./performanceTokens";

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
          bgcolor: PERF_UI.pageBg,
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
          borderBottom: `1px solid ${PERF_UI.rowBorder}`,
          bgcolor: PERF_UI.rowBg,
          flexShrink: 0,
        }}
      >
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ ...PERF_TYPE.name, fontSize: { xs: 15, sm: 16 } }}>
            {title}
          </Typography>
          {subtitle ? (
            <Typography sx={{ ...PERF_TYPE.meta, mt: 0.25 }}>{subtitle}</Typography>
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
            borderTop: `1px solid ${PERF_UI.rowBorder}`,
            bgcolor: PERF_UI.rowBg,
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
      <Typography sx={{ ...PERF_TYPE.name, fontSize: 13, lineHeight: 1.3 }}>
        {primary}
      </Typography>
      {secondary ? (
        <Typography sx={{ mt: 0.1, ...PERF_TYPE.body, fontSize: 12.5 }}>
          {secondary}
        </Typography>
      ) : null}
      {meta ? (
        <Typography sx={{ mt: 0.08, ...PERF_TYPE.meta }}>
          {meta}
        </Typography>
      ) : null}
    </>
  );

  if (!onClick) {
    return (
      <Box sx={{ py: 0.75, borderBottom: `1px solid ${PERF_UI.rowBorder}` }}>
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
        py: 0.75,
        px: 0,
        textAlign: "left",
        border: "none",
        borderBottom: `1px solid ${PERF_UI.rowBorder}`,
        bgcolor: "transparent",
        cursor: "pointer",
        fontFamily: "inherit",
        WebkitTapHighlightColor: "transparent",
        "&:hover": { bgcolor: PERF_UI.kpiBg },
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
        px: 0.85,
        py: 0.35,
        fontSize: 11,
        fontWeight: active ? 500 : 400,
        cursor: "pointer",
        fontFamily: "inherit",
        bgcolor: active ? PERF_UI.teal : "transparent",
        color: active ? "#fff" : PERF_UI.secondary,
        transition: "background-color 0.15s ease, color 0.15s ease",
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
        border: `1px solid ${PERF_UI.rowBorder}`,
        borderRadius: 999,
        px: 0.75,
        py: 0.28,
        fontSize: 11,
        fontWeight: 400,
        color: PERF_UI.secondary,
        bgcolor: PERF_UI.rowBg,
        cursor: "pointer",
        fontFamily: "inherit",
        minWidth: 0,
        maxWidth: 128,
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
