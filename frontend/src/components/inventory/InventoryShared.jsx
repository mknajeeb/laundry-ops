import SearchIcon from "@mui/icons-material/Search";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import AddIcon from "@mui/icons-material/Add";
import RemoveIcon from "@mui/icons-material/Remove";
import FlagOutlinedIcon from "@mui/icons-material/FlagOutlined";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  IconButton,
  InputAdornment,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  ORDER_STATUS_COLORS,
  STATUS_LEVEL_LABELS,
  STOCK_CHECK_QUICK_NOTES,
  VARIANCE_REASON_LABELS,
} from "../../utils/inventoryRoleHelpers";
import {
  formatCurrency,
  formatDateTime,
  INV_INPUT_SX,
  INV_SECTION_CARD_SX,
  parseQtyInput,
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

export function QtyStepper({ value, onChange, min = 0, step = 1, label = "Count on hand" }) {
  const num = value === "" || value == null ? null : Number(value);
  const safe = Number.isFinite(num) ? num : 0;

  const setQty = (next) => {
    const n = Math.max(min, Number.isFinite(next) ? next : min);
    onChange(String(n));
  };

  return (
    <Box>
      {label ? (
        <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ display: "block", mb: 0.75 }}>
          {label}
        </Typography>
      ) : null}
      <Stack direction="row" alignItems="stretch" spacing={1}>
        <IconButton
          aria-label="Decrease count"
          onClick={() => setQty(safe - step)}
          disabled={safe <= min}
          sx={{
            width: 52,
            height: 52,
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 2,
            bgcolor: "background.paper",
          }}
        >
          <RemoveIcon />
        </IconButton>
        <TextField
          fullWidth
          type="number"
          inputMode="decimal"
          value={value ?? ""}
          onChange={(e) => {
            const parsed = parseQtyInput(e.target.value);
            onChange(parsed === "" ? "" : String(parsed));
          }}
          inputProps={{ min, step, style: { textAlign: "center", fontSize: "1.35rem", fontWeight: 700 } }}
          sx={{
            ...INV_INPUT_SX,
            "& .MuiInputBase-root": { height: 52 },
          }}
        />
        <IconButton
          aria-label="Increase count"
          onClick={() => setQty(safe + step)}
          sx={{
            width: 52,
            height: 52,
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 2,
            bgcolor: "background.paper",
          }}
        >
          <AddIcon />
        </IconButton>
      </Stack>
    </Box>
  );
}

export function CategoryProgressBar({ label, done, total }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <Box sx={{ mb: 1.25 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.35 }}>
        <Typography variant="body2" fontWeight={600}>{label}</Typography>
        <Typography variant="caption" color="text.secondary">{done}/{total} · {pct}%</Typography>
      </Stack>
      <LinearProgress
        variant="determinate"
        value={pct}
        sx={{ height: 10, borderRadius: 999, bgcolor: "grey.200", "& .MuiLinearProgress-bar": { borderRadius: 999 } }}
      />
    </Box>
  );
}

export function ItemCountCard({
  item, countValue, noteValue, varianceReason, varianceThreshold = 5,
  statusValue, needsRecount,
  onCountChange, onNoteChange, onVarianceReasonChange, onStatusChange, onRecountChange,
  autosaveLabel,
}) {
  const isStatus = String(item.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
  const current = Number(item.current_on_hand ?? item.on_hand_qty ?? 0);
  const currentStatus = String(item.status_level || "OK").toUpperCase();
  const entered = countValue === "" || countValue == null ? null : Number(countValue);
  const diff = !isStatus && entered != null && !Number.isNaN(entered) ? entered - current : null;
  const needsReason = !needsRecount && diff != null && Math.abs(diff) > Number(varianceThreshold);
  const low = isStatus
    ? ["LOW", "OUT"].includes(currentStatus)
    : current <= Number(item.reorder_level ?? item.reorder_threshold ?? 0);
  const selectedStatus = statusValue || currentStatus;
  const lastAt = item.last_count_at || item.last_count_date;
  const lastBy = item.last_counted_by;

  const toggleQuickNote = (chip) => {
    const cur = String(noteValue || "");
    if (cur.includes(chip)) {
      onNoteChange(cur.replace(chip, "").replace(/\s{2,}/g, " ").replace(/^[,;\s]+|[,;\s]+$/g, "").trim());
    } else {
      onNoteChange(cur ? `${cur.trim()}; ${chip}` : chip);
    }
  };

  const statusBtnSx = (key, active) => {
    const palette = {
      OK: { bg: "#E8F5E9", border: "#2E7D32", color: "#1B5E20" },
      LOW: { bg: "#FFF8E1", border: "#F9A825", color: "#F57F17" },
      OUT: { bg: "#FFEBEE", border: "#C62828", color: "#B71C1C" },
    }[key] || { bg: "grey.100", border: "divider", color: "text.primary" };
    return {
      flex: 1,
      minHeight: 64,
      borderRadius: 2,
      border: "2px solid",
      borderColor: active ? palette.border : "divider",
      bgcolor: active ? palette.bg : "background.paper",
      color: active ? palette.color : "text.secondary",
      fontWeight: 800,
      fontSize: "1rem",
      textTransform: "none",
      boxShadow: active ? `inset 0 0 0 1px ${palette.border}` : "none",
    };
  };

  return (
    <Paper
      elevation={0}
      sx={{
        p: { xs: 1.75, sm: 2 },
        mb: 1.5,
        borderRadius: 2,
        border: "2px solid",
        borderColor: needsRecount ? "info.light" : needsReason ? "error.light" : low ? "warning.light" : "divider",
        bgcolor: needsRecount ? "info.50" : needsReason ? "error.50" : low ? "warning.50" : "background.paper",
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} sx={{ mb: 1 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography fontWeight={700} sx={{ fontSize: { xs: "1.05rem", sm: "1.1rem" } }}>
            {item.name || item.item_name}
          </Typography>
          {lastAt ? (
            <Typography variant="caption" color="text.secondary" display="block">
              Last counted {formatDateTime(lastAt)}{lastBy ? ` · by ${lastBy}` : ""}
            </Typography>
          ) : (
            <Typography variant="caption" color="text.secondary" display="block">Never counted</Typography>
          )}
          {autosaveLabel ? (
            <Typography variant="caption" color="success.main" display="block">{autosaveLabel}</Typography>
          ) : null}
        </Box>
        {item.needs_recount ? <Chip size="small" color="info" label="Needs recount" /> : null}
      </Stack>

      {isStatus ? (
        <Grid container spacing={1.5}>
          <Grid item xs={12}>
            <Typography variant="caption" color="text.secondary" fontWeight={600} sx={{ display: "block", mb: 0.75 }}>
              Tap to set status (autosaves)
            </Typography>
            <Stack direction="row" spacing={1}>
              {Object.entries(STATUS_LEVEL_LABELS).map(([k, lbl]) => (
                <Button
                  key={k}
                  onClick={() => onStatusChange?.(k)}
                  sx={statusBtnSx(k, selectedStatus === k)}
                >
                  {lbl}
                </Button>
              ))}
            </Stack>
          </Grid>
          <Grid item xs={12}>
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
              {STOCK_CHECK_QUICK_NOTES.map((chip) => (
                <Chip
                  key={chip}
                  size="small"
                  label={chip}
                  variant={String(noteValue || "").includes(chip) ? "filled" : "outlined"}
                  color={String(noteValue || "").includes(chip) ? "primary" : "default"}
                  onClick={() => toggleQuickNote(chip)}
                />
              ))}
            </Stack>
            <TextField label="Note (optional)" fullWidth value={noteValue ?? ""} onChange={(e) => onNoteChange(e.target.value)} sx={INV_INPUT_SX} />
          </Grid>
        </Grid>
      ) : (
        <Grid container spacing={1.5}>
          <Grid item xs={4}>
            <Typography variant="caption" color="text.secondary">Current</Typography>
            <Typography variant="h6" fontWeight={700}>{current}</Typography>
          </Grid>
          <Grid item xs={4}>
            <Typography variant="caption" color="text.secondary">Entered</Typography>
            <Typography variant="h6" fontWeight={700}>{needsRecount ? "—" : (entered ?? "—")}</Typography>
          </Grid>
          <Grid item xs={4}>
            <Typography variant="caption" color="text.secondary">Difference</Typography>
            <Typography variant="h6" fontWeight={700} color={diff != null && diff !== 0 ? (diff < 0 ? "error.main" : "success.main") : "text.primary"}>
              {needsRecount ? "—" : (diff != null ? (diff > 0 ? `+${diff}` : diff) : "—")}
            </Typography>
          </Grid>
          <Grid item xs={12}>
            <QtyStepper
              value={countValue ?? ""}
              onChange={(v) => {
                onRecountChange?.(false);
                onCountChange(v);
              }}
            />
          </Grid>
          <Grid item xs={12}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={Boolean(needsRecount)}
                  onChange={(e) => onRecountChange?.(e.target.checked)}
                  icon={<FlagOutlinedIcon />}
                  checkedIcon={<FlagOutlinedIcon />}
                />
              }
              label="Mark for recount (skip applying this count)"
            />
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
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
              {STOCK_CHECK_QUICK_NOTES.map((chip) => (
                <Chip
                  key={chip}
                  size="small"
                  label={chip}
                  variant={String(noteValue || "").includes(chip) ? "filled" : "outlined"}
                  color={String(noteValue || "").includes(chip) ? "primary" : "default"}
                  onClick={() => toggleQuickNote(chip)}
                />
              ))}
            </Stack>
            <TextField label="Note (optional)" fullWidth value={noteValue ?? ""} onChange={(e) => onNoteChange(e.target.value)} sx={INV_INPUT_SX} />
          </Grid>
        </Grid>
      )}
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
