import SearchIcon from "@mui/icons-material/Search";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Grid,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { ORDER_STATUS_COLORS, VARIANCE_REASON_LABELS } from "../../utils/inventoryRoleHelpers";
import {
  formatCurrency,
  INV_INPUT_SX,
  INV_SECTION_CARD_SX,
} from "../../utils/inventoryHelpers";

export function SectionCard({ title, subtitle, children, action }) {
  return (
    <Paper elevation={0} sx={INV_SECTION_CARD_SX}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: subtitle ? 0.5 : 1.5 }}>
        <Box>
          <Typography variant="h6" fontWeight={700} sx={{ fontSize: { xs: "1.05rem", sm: "1.15rem" } }}>
            {title}
          </Typography>
          {subtitle ? (
            <Typography variant="body2" color="text.secondary">
              {subtitle}
            </Typography>
          ) : null}
        </Box>
        {action}
      </Stack>
      {children}
    </Paper>
  );
}

export function SummaryStatCard({ label, value, color = "primary.main" }) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: "1px solid",
        borderColor: "divider",
        bgcolor: "grey.50",
        height: "100%",
      }}
    >
      <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={800} color={color} sx={{ mt: 0.5, fontSize: { xs: "1.1rem", sm: "1.25rem" } }}>
        {value}
      </Typography>
    </Paper>
  );
}

export function CategoryAccordion({ category, defaultExpanded, children }) {
  return (
    <Accordion
      defaultExpanded={defaultExpanded}
      disableGutters
      elevation={0}
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "12px !important",
        mb: 1.5,
        "&:before": { display: "none" },
        overflow: "hidden",
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 2, minHeight: 52 }}>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography fontWeight={700}>{category.name}</Typography>
          <Chip label={`${category.items?.length || 0} items`} size="small" variant="outlined" />
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 2, pt: 0, pb: 2 }}>{children}</AccordionDetails>
    </Accordion>
  );
}

export function OrderStatusBadge({ status }) {
  const key = String(status || "").toUpperCase();
  const label = key.replace(/_/g, " ");
  return <Chip size="small" label={label} color={ORDER_STATUS_COLORS[key] || "default"} variant={key === "DRAFT" ? "outlined" : "filled"} />;
}

export function SearchField({ value, onChange, placeholder = "Search items…" }) {
  return (
    <TextField
      fullWidth
      size="medium"
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> }}
      sx={{ mb: 2, ...INV_INPUT_SX }}
    />
  );
}

export function ItemCountCard({
  item, countValue, noteValue, varianceReason, varianceThreshold = 5,
  onCountChange, onNoteChange, onVarianceReasonChange,
}) {
  const current = Number(item.current_on_hand ?? item.on_hand_qty ?? 0);
  const entered = countValue === "" || countValue == null ? null : Number(countValue);
  const diff = entered != null && !Number.isNaN(entered) ? entered - current : null;
  const needsReason = diff != null && Math.abs(diff) > Number(varianceThreshold);
  const low = current <= Number(item.reorder_level ?? item.reorder_threshold ?? 0);
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        mb: 1.5,
        borderRadius: 2,
        border: "2px solid",
        borderColor: needsReason ? "error.light" : low ? "warning.light" : "divider",
        bgcolor: needsReason ? "error.50" : low ? "warning.50" : "background.paper",
      }}
    >
      <Typography fontWeight={700} sx={{ mb: 1 }}>{item.name || item.item_name}</Typography>
      <Grid container spacing={1.5}>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">Current</Typography>
          <Typography variant="h6" fontWeight={700}>{current}</Typography>
        </Grid>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">Entered</Typography>
          <Typography variant="h6" fontWeight={700}>{entered ?? "—"}</Typography>
        </Grid>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">Difference</Typography>
          <Typography variant="h6" fontWeight={700} color={diff != null && diff !== 0 ? (diff < 0 ? "error.main" : "success.main") : "text.primary"}>
            {diff != null ? (diff > 0 ? `+${diff}` : diff) : "—"}
          </Typography>
        </Grid>
        <Grid item xs={12}>
          <TextField label="Count on hand" type="number" fullWidth value={countValue ?? ""} onChange={(e) => onCountChange(e.target.value)} inputProps={{ min: 0, step: 1 }} sx={INV_INPUT_SX} />
        </Grid>
        {needsReason ? (
          <Grid item xs={12}>
            <TextField select label="Reason for difference (required)" fullWidth value={varianceReason || ""} onChange={(e) => onVarianceReasonChange?.(e.target.value)} sx={INV_INPUT_SX}>
              {Object.entries(VARIANCE_REASON_LABELS).map(([k, lbl]) => (
                <MenuItem key={k} value={k}>{lbl}</MenuItem>
              ))}
            </TextField>
          </Grid>
        ) : null}
        <Grid item xs={12}>
          <TextField label="Note (optional)" fullWidth value={noteValue ?? ""} onChange={(e) => onNoteChange(e.target.value)} sx={INV_INPUT_SX} />
        </Grid>
      </Grid>
    </Paper>
  );
}

export function CurrencyField({ label, value, onChange, ...rest }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={onChange}
      type="number"
      inputMode="decimal"
      fullWidth
      InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }}
      sx={INV_INPUT_SX}
      {...rest}
    />
  );
}

export function LoadingBlock({ message = "Loading…" }) {
  return (
    <Stack alignItems="center" justifyContent="center" sx={{ py: 6 }}>
      <CircularProgress size={32} />
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
        {message}
      </Typography>
    </Stack>
  );
}

export function StatusAlert({ message, onClose }) {
  if (!message?.text) return null;
  return (
    <Alert severity={message.type === "error" ? "error" : "success"} onClose={onClose} sx={{ mb: 2 }}>
      {message.text}
    </Alert>
  );
}

export function EstimatedLineTotal({ qty, unitCost }) {
  const total = Number(qty || 0) * Number(unitCost || 0);
  return (
    <Typography variant="body2" color="text.secondary">
      Est. {formatCurrency(total)}
    </Typography>
  );
}

export function StickyActionBar({ children, showOnDesktop = false }) {
  return (
    <Box
      sx={{
        ...(showOnDesktop ? {} : { display: { xs: "block", md: "none" } }),
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 1100,
        p: 2,
        pb: "calc(16px + env(safe-area-inset-bottom))",
        bgcolor: "background.paper",
        borderTop: "1px solid",
        borderColor: "divider",
        boxShadow: "0 -4px 12px rgba(0,0,0,0.08)",
      }}
    >
      <Stack direction="row" spacing={1.5} justifyContent="stretch">
        {children}
      </Stack>
    </Box>
  );
}
