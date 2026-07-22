import { useCallback, useEffect, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
  CircularProgress,
  Alert,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  getVeewashStep1BagDetail,
  getVeewashStep1Drilldown,
  postVeewashStep1Correction,
} from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";
import FoldingUserSelect from "../folding/FoldingUserSelect";
import { PayrollDateTimeField } from "../PayrollDateTimeField";

function defaultRackForService(service) {
  return String(service).toUpperCase() === "HD" ? "workitems-added" : "VeeWash Dirty";
}

/** Normalize API timestamps into datetime-local / dayjs-friendly ET strings. */
function toPickerValue(v) {
  if (!v) return "";
  const s = String(v).trim().replace(" ", "T");
  // Strip timezone offset / seconds for the picker value we round-trip.
  const m = s.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  return m ? m[1] : s.slice(0, 16);
}

const REASON_LABELS = {
  DISAPPEARED_WITHOUT_COMPLETION: "Disappeared without completion",
  COMPLETED_WITHOUT_RECOGNIZED_ENTRY: "Completed without recognized entry",
  WF_ZERO_OR_MISSING_POST_WEIGHT: "Zero or missing WF post weight",
  WF_ZERO_OR_MISSING_WEIGHT: "Zero or missing WF post weight",
  SERVICE_CLASSIFICATION_MISMATCH: "Service classification mismatch",
  COMPLETION_DETAILS_MISSING: "Completion details missing",
};

const PAGE_SIZE = 25;

function fmtTs(v) {
  if (!v) return "—";
  const s = String(v);
  return s.length > 19 ? s.slice(0, 19).replace("T", " ") : s.replace("T", " ");
}

export default function Step1MetricDrawer({
  open,
  onClose,
  selectedDateEt,
  metric,
  serviceFilter = "all",
  rushFilter = "all",
  title,
  onCorrected,
  readOnly = false,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [bags, setBags] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [detailLoading, setDetailLoading] = useState({});
  const [actionBag, setActionBag] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(
    async (nextPage = 1) => {
      if (!open || !selectedDateEt || !metric) return;
      setLoading(true);
      setError("");
      setExpanded(null);
      try {
        const res = await getVeewashStep1Drilldown({
          date: selectedDateEt,
          metric,
          service: serviceFilter,
          rush: rushFilter,
          page: nextPage,
          page_size: PAGE_SIZE,
          include_details: false,
        });
        const data = res?.data || {};
        setBags(data.bags || []);
        setPage(data.pagination?.page || nextPage);
        setTotal(data.pagination?.total ?? (data.bags || []).length);
        setHasMore(Boolean(data.pagination?.has_more));
      } catch (e) {
        setError(e?.response?.data?.error || e?.message || "Failed to load drill-down");
        setBags([]);
        setTotal(0);
        setHasMore(false);
      } finally {
        setLoading(false);
      }
    },
    [open, selectedDateEt, metric, serviceFilter, rushFilter]
  );

  useEffect(() => {
    load(1);
  }, [load]);

  const loadBagDetail = async (bagId) => {
    if (!bagId || !selectedDateEt || !metric) return;
    setDetailLoading((m) => ({ ...m, [bagId]: true }));
    try {
      const res = await getVeewashStep1BagDetail({
        date: selectedDateEt,
        metric,
        service: serviceFilter,
        rush: rushFilter,
        bag_id: bagId,
        include_details: true,
      });
      const detail = (res?.data?.bags || [])[0];
      if (!detail) return;
      setBags((prev) =>
        prev.map((b) =>
          b.bag_id === bagId
            ? {
                ...b,
                ...detail,
                scans: detail.scans || [],
                corrections: detail.corrections || [],
                _detailsLoaded: true,
              }
            : b
        )
      );
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || `Failed to load details for ${bagId}`);
    } finally {
      setDetailLoading((m) => ({ ...m, [bagId]: false }));
    }
  };

  const onExpand = (bagId) => {
    const next = expanded === bagId ? null : bagId;
    setExpanded(next);
    if (!next) return;
    const bag = bags.find((b) => b.bag_id === bagId);
    if (bag && !bag._detailsLoaded) {
      loadBagDetail(bagId);
    }
  };

  const startAction = (bag, action) => {
    setActionBag(bag.bag_id);
    setForm({
      action,
      bag_id: bag.bag_id,
      selected_date_et: selectedDateEt,
      reason: "",
      employee: bag.completed_by || "",
      completion_at: toPickerValue(bag.completion_at),
      entry_at: toPickerValue(bag.entry_at) || `${selectedDateEt || ""}T09:00`.slice(0, 16),
      service_type: bag.service_type || "WF",
      rack: defaultRackForService(bag.service_type || "WF"),
      weight_lbs:
        bag.post_weight_lbs != null && Number(bag.post_weight_lbs) > 0
          ? String(bag.post_weight_lbs)
          : bag.weight_lbs != null && Number(bag.weight_lbs) > 0
            ? String(bag.weight_lbs)
            : "",
      weight_at: toPickerValue(selectedDateEt ? `${selectedDateEt}T12:00` : ""),
    });
  };

  const submitCorrection = async () => {
    if (!form.reason?.trim()) {
      setError("Correction reason is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = {
        ...form,
        completion_at: form.completion_at ? form.completion_at.replace(" ", "T") : undefined,
        entry_at: form.entry_at ? form.entry_at.replace(" ", "T") : undefined,
        rack: form.action === "correct_entry" && form.service_type !== "HD" ? form.rack : undefined,
        weight_at: form.weight_at ? form.weight_at.replace(" ", "T") : undefined,
        weight_lbs: form.weight_lbs !== "" ? Number(form.weight_lbs) : undefined,
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        setError(res?.data?.error || "Correction failed");
        return;
      }
      setActionBag(null);
      await load(page);
      onCorrected?.();
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Correction failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: "100%", sm: 520, md: 640 },
          p: 2,
          bgcolor: "#fff",
        },
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Box>
          <Typography variant="h6" fontWeight={800}>
            {title || metric}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {selectedDateEt} · service={serviceFilter} · rush={rushFilter}
          </Typography>
        </Box>
        <Button onClick={onClose}>Close</Button>
      </Stack>
      <Divider sx={{ mb: 1.5 }} />
      {error ? (
        <Alert
          severity="error"
          sx={{ mb: 1 }}
          onClose={() => setError("")}
          action={
            <Button color="inherit" size="small" onClick={() => load(page)}>
              Retry
            </Button>
          }
        >
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <Stack spacing={1}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="body2" color="text.secondary">
              {total} bag{total === 1 ? "" : "s"}
              {total > PAGE_SIZE ? ` · page ${page}` : ""}
            </Typography>
            <Button size="small" onClick={() => load(page)} disabled={loading}>
              Refresh
            </Button>
          </Stack>
          {bags.map((bag) => {
            const openRow = expanded === bag.bag_id;
            const loadingDetail = Boolean(detailLoading[bag.bag_id]);
            return (
              <Accordion
                key={bag.bag_id}
                expanded={openRow}
                onChange={() => onExpand(bag.bag_id)}
                disableGutters
                elevation={0}
                sx={{ border: "1px solid #e2e8f0", borderRadius: 1, "&:before": { display: "none" } }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ width: "100%", pr: 1 }}>
                    <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Typography fontFamily="monospace" fontWeight={700}>
                        {bag.bag_id}
                      </Typography>
                      <Chip size="small" label={bag.service_type || "—"} />
                      <Chip size="small" label={bag.rush_flag || "—"} variant="outlined" />
                      <Chip
                        size="small"
                        label={bag.dashboard_status || "—"}
                        color="warning"
                        variant="outlined"
                      />
                    </Stack>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {bag.customer_name || "—"} · {bag.entry_class || "—"} · Pre Weight{" "}
                      {bag.pre_weight_lbs ?? "—"} · Post Weight {bag.post_weight_lbs ?? "—"}
                    </Typography>
                    {(bag.reason_codes || []).length > 0 ? (
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                        {(bag.reason_codes || []).map((c) => (
                          <Chip
                            key={c}
                            size="small"
                            label={REASON_LABELS[c] || c}
                            sx={{ height: 20, fontSize: "0.68rem" }}
                          />
                        ))}
                      </Stack>
                    ) : null}
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>
                    Entry: {bag.entry_source || "—"} @ {fmtTs(bag.entry_at)} · Completion:{" "}
                    {fmtTs(bag.completion_at)} by {bag.completed_by || "—"} · Portal:{" "}
                    {bag.portal_status || "—"} · Last seen: {fmtTs(bag.last_seen_at)}
                  </Typography>
                  <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1, mb: 0.5 }}>
                    Scan chronology (ET)
                  </Typography>
                  {loadingDetail ? (
                    <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
                      <CircularProgress size={22} />
                    </Box>
                  ) : (
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Time</TableCell>
                          <TableCell>Purpose</TableCell>
                          <TableCell>Rack</TableCell>
                          <TableCell>Employee</TableCell>
                          <TableCell>Wt</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(bag.scans || []).map((s, i) => (
                          <TableRow key={`${bag.bag_id}-${i}`}>
                            <TableCell sx={{ whiteSpace: "nowrap" }}>
                              {fmtTs(s.scanned_at_parsed)}
                            </TableCell>
                            <TableCell>{s.purpose || "—"}</TableCell>
                            <TableCell>{s.rack || "—"}</TableCell>
                            <TableCell>{s.user_name || "—"}</TableCell>
                            <TableCell>{s.weight_lbs ?? "—"}</TableCell>
                          </TableRow>
                        ))}
                        {(bag.scans || []).length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={5}>No scans</TableCell>
                          </TableRow>
                        ) : null}
                      </TableBody>
                    </Table>
                  )}

                  <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1.5, mb: 0.5 }}>
                    System result
                  </Typography>
                  <Typography variant="caption" display="block">
                    Outcome {bag.system_result?.outcome || "—"} · Canonical{" "}
                    {bag.system_result?.canonical_status || "—"} · Reasons{" "}
                    {(bag.system_result?.reason_codes || []).join(", ") || "—"}
                  </Typography>
                  {!loadingDetail && (bag.corrections || []).length > 0 ? (
                    <>
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1, mb: 0.5 }}>
                        Manager corrections
                      </Typography>
                      {(bag.corrections || []).slice(0, 5).map((c, i) => (
                        <Typography key={i} variant="caption" display="block">
                          {fmtTs(c.created_at)} · {c.action} · {c.actor_display_name || "—"} ·{" "}
                          {c.reason_text}
                        </Typography>
                      ))}
                    </>
                  ) : null}

                  <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
                    {readOnly ? (
                      <Typography variant="caption" color="text.secondary">
                        Shift is closed — reopen to make corrections.
                      </Typography>
                    ) : (
                      <>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => startAction(bag, "mark_completed")}
                        >
                          Mark completed
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => startAction(bag, "return_pending")}
                        >
                          Return to pending
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => startAction(bag, "correct_entry")}
                        >
                          Correct entry
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => startAction(bag, "correct_weight")}
                        >
                          Correct weight
                        </Button>
                        <Button
                          size="small"
                          color="error"
                          variant="outlined"
                          onClick={() => startAction(bag, "exclude")}
                        >
                          Exclude
                        </Button>
                      </>
                    )}
                  </Stack>

                  {!readOnly && actionBag === bag.bag_id ? (
                    <Box
                      sx={{ mt: 1.5, p: 1.25, bgcolor: VEEWASH_DASHBOARD.primaryBlueLight, borderRadius: 1 }}
                    >
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
                        {form.action}
                      </Typography>
                      <Stack spacing={1}>
                        {(form.action === "mark_completed" || form.action === "correct_completion") && (
                          <>
                            <FoldingUserSelect
                              label="Completed by"
                              value={form.employee || ""}
                              onChange={(name) => setForm((f) => ({ ...f, employee: name }))}
                              allowEmpty={false}
                              sx={{ width: "100%", minWidth: 0 }}
                            />
                            <PayrollDateTimeField
                              label="Completion date & time (ET)"
                              value={form.completion_at || ""}
                              onChange={(v) => setForm((f) => ({ ...f, completion_at: v }))}
                            />
                          </>
                        )}
                        {form.action === "correct_entry" && (
                          <>
                            <FormControl size="small" fullWidth>
                              <InputLabel>Service</InputLabel>
                              <Select
                                label="Service"
                                value={form.service_type || "WF"}
                                onChange={(e) => {
                                  const nextService = e.target.value;
                                  setForm((f) => ({
                                    ...f,
                                    service_type: nextService,
                                    rack:
                                      f.rack === defaultRackForService(f.service_type)
                                        ? defaultRackForService(nextService)
                                        : f.rack,
                                  }));
                                }}
                              >
                                <MenuItem value="WF">WF</MenuItem>
                                <MenuItem value="HD">HD</MenuItem>
                              </Select>
                            </FormControl>
                            <PayrollDateTimeField
                              label="Entry date & time (ET)"
                              value={form.entry_at || ""}
                              onChange={(v) => setForm((f) => ({ ...f, entry_at: v }))}
                            />
                            <TextField
                              size="small"
                              label="Rack"
                              value={form.rack || ""}
                              disabled={form.service_type === "HD"}
                              helperText={
                                form.service_type === "HD"
                                  ? "HD entries use workitems-added, not a rack"
                                  : undefined
                              }
                              onChange={(e) => setForm((f) => ({ ...f, rack: e.target.value }))}
                            />
                          </>
                        )}
                        {form.action === "correct_weight" && (
                          <>
                            <TextField
                              size="small"
                              type="number"
                              label="Post Weight lbs (>0)"
                              value={form.weight_lbs}
                              onChange={(e) => setForm((f) => ({ ...f, weight_lbs: e.target.value }))}
                              helperText={`Pre Weight: ${bag.pre_weight_lbs ?? "—"} (informational). Review Required only when Post Weight is missing or ≤0.`}
                              inputProps={{ min: 0.1, step: 0.1 }}
                            />
                            <PayrollDateTimeField
                              label="Weight date & time (ET)"
                              value={form.weight_at || ""}
                              onChange={(v) => setForm((f) => ({ ...f, weight_at: v }))}
                            />
                            <FoldingUserSelect
                              label="Weight employee"
                              value={form.employee || ""}
                              onChange={(name) => setForm((f) => ({ ...f, employee: name }))}
                              allowEmpty={false}
                              sx={{ width: "100%", minWidth: 0 }}
                            />
                          </>
                        )}
                        <TextField
                          size="small"
                          required
                          label="Correction reason"
                          value={form.reason || ""}
                          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
                          multiline
                          minRows={2}
                        />
                        <Stack direction="row" spacing={1}>
                          <Button variant="contained" disabled={saving} onClick={submitCorrection}>
                            {saving ? "Saving…" : "Save correction"}
                          </Button>
                          <Button onClick={() => setActionBag(null)}>Cancel</Button>
                        </Stack>
                      </Stack>
                    </Box>
                  ) : null}
                </AccordionDetails>
              </Accordion>
            );
          })}
          {(page > 1 || hasMore) && (
            <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ pt: 1 }}>
              <Button size="small" disabled={page <= 1 || loading} onClick={() => load(page - 1)}>
                Previous
              </Button>
              <Button size="small" disabled={!hasMore || loading} onClick={() => load(page + 1)}>
                Next
              </Button>
            </Stack>
          )}
        </Stack>
      )}
    </Drawer>
  );
}
