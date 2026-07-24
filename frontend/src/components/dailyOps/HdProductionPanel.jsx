import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  DialogContent,
  DialogTitle,
  Drawer,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import {
  exportDailyOperationsHdProductionUrl,
  getDailyOperationsHdProduction,
  getDailyOperationsHdProductionDetail,
  saveDailyOperationsHdProduction,
  undoDailyOperationsHdProduction,
} from "../../api";

function money(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const EXTERNAL_ID = "external_unknown";

function emptyDraft(detail) {
  const p = detail?.production || {};
  const washedExternal = Boolean(p.washed_by_override_name) && !p.washed_by_user_id;
  const foldedExternal = Boolean(p.folded_by_override_name) && !p.folded_by_user_id;
  return {
    version: p.version ?? 0,
    washed_by_user_id: washedExternal ? EXTERNAL_ID : p.washed_by_user_id ?? "",
    washed_by_override_name: p.washed_by_override_name || "",
    washed_by_external: washedExternal,
    folded_by_user_id: foldedExternal ? EXTERNAL_ID : p.folded_by_user_id ?? "",
    folded_by_override_name: p.folded_by_override_name || "",
    folded_by_external: foldedExternal,
    total_items: p.total_items != null ? String(p.total_items) : "",
    revenue: p.revenue != null ? String(p.revenue) : "",
    zero_items_reason_code: p.zero_items_reason_code || "",
    zero_items_reason_note: p.zero_items_reason_note || "",
    zero_revenue_reason_code: p.zero_revenue_reason_code || "",
    zero_revenue_reason_note: p.zero_revenue_reason_note || "",
    notes: p.notes || "",
    reason: "",
  };
}

function buildSaveBody(draft) {
  const washedExternal = draft.washed_by_user_id === EXTERNAL_ID || draft.washed_by_external;
  const foldedExternal = draft.folded_by_user_id === EXTERNAL_ID || draft.folded_by_external;
  return {
    version: draft.version,
    reason: draft.reason,
    notes: draft.notes,
    washed_by_user_id: washedExternal ? null : draft.washed_by_user_id || null,
    washed_by_external: washedExternal,
    washed_by_override_name: washedExternal ? draft.washed_by_override_name : null,
    washed_by_external_reason: washedExternal ? draft.reason : null,
    folded_by_user_id: foldedExternal ? null : draft.folded_by_user_id || null,
    folded_by_external: foldedExternal,
    folded_by_override_name: foldedExternal ? draft.folded_by_override_name : null,
    folded_by_external_reason: foldedExternal ? draft.reason : null,
    total_items: draft.total_items === "" ? null : Number(draft.total_items),
    revenue: draft.revenue === "" ? null : Number(draft.revenue),
    zero_items_reason_code: draft.zero_items_reason_code || null,
    zero_items_reason_note: draft.zero_items_reason_note || null,
    zero_revenue_reason_code: draft.zero_revenue_reason_code || null,
    zero_revenue_reason_note: draft.zero_revenue_reason_note || null,
  };
}

function Row({ label, value, strong }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={strong ? 700 : 500} textAlign="right">
        {value}
      </Typography>
    </Stack>
  );
}

export default function HdProductionPanel({ dateEt, onSaved }) {
  const isMobile = useMediaQuery("(max-width:900px)");
  const [statusFilter, setStatusFilter] = useState("");
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedBag, setSelectedBag] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [undoReason, setUndoReason] = useState("");

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (statusFilter) params.status = statusFilter;
      const payload = (await getDailyOperationsHdProduction(dateEt, params)).data;
      setQueue(payload);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load HD production");
      setQueue(null);
    } finally {
      setLoading(false);
    }
  }, [dateEt, statusFilter]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const openBag = async (bagId) => {
    setError("");
    setSelectedBag(bagId);
    try {
      const payload = (await getDailyOperationsHdProductionDetail(dateEt, bagId)).data;
      setDetail(payload);
      setDraft(emptyDraft(payload));
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load HD bag");
      setDetail(null);
      setDraft(null);
    }
  };

  const closeDetail = () => {
    setSelectedBag(null);
    setDetail(null);
    setDraft(null);
    setUndoReason("");
  };

  const save = async () => {
    if (!draft || !selectedBag) return;
    setSaving(true);
    setError("");
    try {
      const payload = (await saveDailyOperationsHdProduction(dateEt, selectedBag, buildSaveBody(draft))).data;
      if (!payload?.ok) {
        if (payload?.error === "conflict") {
          setError("Conflict — reloading current record");
          await openBag(selectedBag);
        } else {
          setError(payload?.error || (payload?.errors || []).join(", ") || "Save failed");
        }
        return;
      }
      setDetail((d) => ({ ...d, production: payload.production }));
      setDraft(emptyDraft({ production: payload.production }));
      await loadQueue();
      onSaved?.();
    } catch (e) {
      const data = e?.response?.data;
      if (e?.response?.status === 409) {
        setError("Conflict — reload required");
        if (data?.current_record) {
          setDraft(emptyDraft({ production: data.current_record }));
        }
      } else {
        setError(data?.error || (data?.errors || []).join(", ") || e?.message || "Save failed");
      }
    } finally {
      setSaving(false);
    }
  };

  const undoLatest = async () => {
    if (!selectedBag || !undoReason.trim()) {
      setError("Undo reason required");
      return;
    }
    setSaving(true);
    try {
      const payload = (
        await undoDailyOperationsHdProduction(dateEt, selectedBag, { reason: undoReason.trim() })
      ).data;
      if (!payload?.ok) {
        setError(payload?.error || "Undo failed");
        return;
      }
      setDetail((d) => ({ ...d, production: payload.production }));
      setDraft(emptyDraft({ production: payload.production }));
      setUndoReason("");
      await loadQueue();
      onSaved?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Undo failed");
    } finally {
      setSaving(false);
    }
  };

  const employees = queue?.employee_options || detail?.employee_options || [];
  const zeroRevCodes = queue?.reason_codes?.zero_revenue || detail?.reason_codes?.zero_revenue || [];
  const zeroItemCodes = queue?.reason_codes?.zero_items || detail?.reason_codes?.zero_items || [];
  const summary = queue?.summary || {};
  const items = queue?.items || [];

  const workerSelect = (role) => {
    const key = `${role}_by_user_id`;
    const extKey = `${role}_by_external`;
    const overrideKey = `${role}_by_override_name`;
    return (
      <Stack spacing={1}>
        <TextField
          select
          size="small"
          label={role === "washed" ? "Washed By" : "Folded By"}
          value={draft[key] === "" || draft[key] == null ? "" : draft[key]}
          onChange={(e) => {
            const v = e.target.value;
            setDraft((d) => ({
              ...d,
              [key]: v,
              [extKey]: v === EXTERNAL_ID,
              [overrideKey]: v === EXTERNAL_ID ? d[overrideKey] : "",
            }));
          }}
          fullWidth
        >
          <MenuItem value="">—</MenuItem>
          {employees.map((e) => (
            <MenuItem key={String(e.id)} value={e.is_external ? EXTERNAL_ID : e.user_id}>
              {e.display_name}
            </MenuItem>
          ))}
        </TextField>
        {draft[extKey] || draft[key] === EXTERNAL_ID ? (
          <TextField
            size="small"
            label="Worker name override"
            value={draft[overrideKey]}
            onChange={(e) => setDraft((d) => ({ ...d, [overrideKey]: e.target.value }))}
            fullWidth
            required
          />
        ) : null}
      </Stack>
    );
  };

  const detailBody =
    detail && draft ? (
      <Stack spacing={2} sx={{ pb: isMobile ? 10 : 2 }}>
        <Box>
          <Typography variant="subtitle1" fontWeight={700}>
            Bag {detail.bag_id}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Service = HD · Rush {detail.membership?.rush_status || "—"} · Workload entry{" "}
            {detail.membership?.first_available || "—"}
          </Typography>
          <Chip size="small" sx={{ mt: 0.5 }} label={detail.production?.status || "NOT_RECORDED"} />
          {detail.membership?.orphan_production_fact ? (
            <Alert severity="warning" sx={{ mt: 1 }}>
              Reconciliation exception: production fact exists but bag is not HD in membership.
            </Alert>
          ) : null}
        </Box>

        {workerSelect("washed")}
        {workerSelect("folded")}

        <TextField
          size="small"
          type="number"
          label="Total Items"
          value={draft.total_items}
          onChange={(e) => setDraft((d) => ({ ...d, total_items: e.target.value }))}
          inputProps={{ step: 1, min: 0 }}
        />
        {draft.total_items === "0" ? (
          <>
            <TextField
              select
              size="small"
              label="Zero items reason"
              value={draft.zero_items_reason_code}
              onChange={(e) => setDraft((d) => ({ ...d, zero_items_reason_code: e.target.value }))}
            >
              {zeroItemCodes.map((c) => (
                <MenuItem key={c} value={c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="Zero items note"
              value={draft.zero_items_reason_note}
              onChange={(e) => setDraft((d) => ({ ...d, zero_items_reason_note: e.target.value }))}
            />
          </>
        ) : null}

        <TextField
          size="small"
          type="number"
          label="Revenue"
          value={draft.revenue}
          onChange={(e) => setDraft((d) => ({ ...d, revenue: e.target.value }))}
          inputProps={{ step: "0.01", min: "0" }}
        />
        {draft.revenue === "0" || draft.revenue === "0.0" || draft.revenue === "0.00" ? (
          <>
            <TextField
              select
              size="small"
              label="Zero revenue reason"
              value={draft.zero_revenue_reason_code}
              onChange={(e) => setDraft((d) => ({ ...d, zero_revenue_reason_code: e.target.value }))}
            >
              {zeroRevCodes.map((c) => (
                <MenuItem key={c} value={c}>
                  {c}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="Zero revenue note"
              value={draft.zero_revenue_reason_note}
              onChange={(e) => setDraft((d) => ({ ...d, zero_revenue_reason_note: e.target.value }))}
            />
          </>
        ) : null}

        <TextField
          size="small"
          label="Notes"
          multiline
          minRows={2}
          value={draft.notes}
          onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
        />
        <TextField
          size="small"
          label="Save reason"
          required
          value={draft.reason}
          onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))}
        />

        {(detail.audits || []).length > 0 ? (
          <Paper variant="outlined" sx={{ p: 1.5 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Audit history
            </Typography>
            {detail.audits.slice(0, 8).map((a) => (
              <Typography key={a.id} variant="caption" color="text.secondary" display="block">
                v{a.version_before}→{a.version_after} {a.action}
                {a.is_undo ? " (undo)" : ""} · {a.created_at}
              </Typography>
            ))}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
              <TextField
                size="small"
                label="Undo reason"
                value={undoReason}
                onChange={(e) => setUndoReason(e.target.value)}
                sx={{ flex: 1 }}
              />
              <Button size="small" color="warning" variant="outlined" onClick={undoLatest} disabled={saving}>
                Undo latest
              </Button>
            </Stack>
          </Paper>
        ) : null}

        {!isMobile ? (
          <Button variant="contained" onClick={save} disabled={saving || !detail.permissions?.can_save}>
            {saving ? "Saving…" : "Save HD Production"}
          </Button>
        ) : null}
      </Stack>
    ) : selectedBag ? (
      <Box sx={{ py: 4, textAlign: "center" }}>
        <CircularProgress size={28} />
      </Box>
    ) : null;

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ flex: 1 }}>
          HD Production
        </Typography>
        <TextField
          select
          size="small"
          label="Status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="">All</MenuItem>
          <MenuItem value="NOT_RECORDED">Not Recorded</MenuItem>
          <MenuItem value="PARTIALLY_RECORDED">Partial</MenuItem>
          <MenuItem value="COMPLETE">Complete</MenuItem>
        </TextField>
        <Button size="small" variant="outlined" onClick={loadQueue} disabled={loading}>
          Refresh
        </Button>
        <Button
          size="small"
          variant="outlined"
          href={exportDailyOperationsHdProductionUrl(dateEt)}
          target="_blank"
          rel="noreferrer"
        >
          Excel / CSV
        </Button>
        {loading ? <CircularProgress size={18} /> : null}
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" },
          gap: 1,
          mb: 1.5,
        }}
      >
        {[
          ["HD Orders", String(summary.hd_orders_available ?? 0)],
          ["Not Recorded", String(summary.not_recorded ?? 0)],
          ["Partial", String(summary.partially_recorded ?? 0)],
          ["Complete", String(summary.complete ?? 0)],
          ["Complete Items", String(summary.complete_total_items ?? 0)],
          ["Complete HD Revenue", money(summary.complete_hd_revenue)],
          ["Partial Revenue (excluded)", money(summary.partial_hd_revenue_entered)],
        ].map(([label, value]) => (
          <Paper key={label} variant="outlined" sx={{ p: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {label}
            </Typography>
            <Typography fontWeight={700}>{value}</Typography>
          </Paper>
        ))}
      </Box>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {error}
        </Alert>
      ) : null}

      {queue && !queue.available ? (
        <Alert severity="info">{queue.message || "HD Production unavailable"}</Alert>
      ) : isMobile ? (
        <Stack spacing={1}>
          {items.map((it) => (
            <Paper key={it.bag_id} variant="outlined" sx={{ p: 1.25 }} onClick={() => openBag(it.bag_id)}>
              <Typography fontWeight={700}>{it.bag_id}</Typography>
              <Typography variant="body2" color="text.secondary">
                {it.status} · {money(it.revenue)}
              </Typography>
            </Paper>
          ))}
        </Stack>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: selectedBag ? "minmax(280px, 1fr) minmax(360px, 1.1fr)" : "1fr",
            gap: 2,
          }}
        >
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Bag</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Washed</TableCell>
                  <TableCell>Folded</TableCell>
                  <TableCell align="right">Items</TableCell>
                  <TableCell align="right">Revenue</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((it) => (
                  <TableRow
                    key={it.bag_id}
                    hover
                    selected={selectedBag === it.bag_id}
                    sx={{ cursor: "pointer" }}
                    onClick={() => openBag(it.bag_id)}
                  >
                    <TableCell>{it.bag_id}</TableCell>
                    <TableCell>{it.status}</TableCell>
                    <TableCell>{it.washed_by_name_snapshot || "—"}</TableCell>
                    <TableCell>{it.folded_by_name_snapshot || "—"}</TableCell>
                    <TableCell align="right">{it.total_items ?? "—"}</TableCell>
                    <TableCell align="right">{money(it.revenue)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
          {selectedBag ? (
            <Box>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle2" fontWeight={700}>
                  HD detail
                </Typography>
                <IconButton size="small" onClick={closeDetail}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Stack>
              {detailBody}
            </Box>
          ) : null}
        </Box>
      )}

      {isMobile ? (
        <Drawer anchor="bottom" open={Boolean(selectedBag)} onClose={closeDetail} PaperProps={{ sx: { maxHeight: "92vh" } }}>
          <Box sx={{ p: 2 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <DialogTitle sx={{ p: 0, fontSize: "1.1rem" }}>HD Production</DialogTitle>
              <IconButton onClick={closeDetail}>
                <CloseIcon />
              </IconButton>
            </Stack>
            <DialogContent sx={{ p: 0 }}>{detailBody}</DialogContent>
            <Box sx={{ position: "sticky", bottom: 0, pt: 1.5, bgcolor: "background.paper" }}>
              <Button fullWidth variant="contained" onClick={save} disabled={saving || !draft}>
                {saving ? "Saving…" : "Save HD Production"}
              </Button>
            </Box>
          </Box>
        </Drawer>
      ) : null}
    </Paper>
  );
}
