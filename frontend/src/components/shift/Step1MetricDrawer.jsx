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
import { getVeewashStep1Drilldown, postVeewashStep1Correction } from "../../api";
import { VEEWASH_DASHBOARD } from "../../theme/veewashDashboard";

const REASON_LABELS = {
  DISAPPEARED_WITHOUT_COMPLETION: "Disappeared without completion",
  COMPLETED_WITHOUT_RECOGNIZED_ENTRY: "Completed without recognized entry",
  WF_ZERO_OR_MISSING_WEIGHT: "Zero or missing WF weight",
  SERVICE_CLASSIFICATION_MISMATCH: "Service classification mismatch",
  COMPLETION_DETAILS_MISSING: "Completion details missing",
};

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
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [bags, setBags] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [actionBag, setActionBag] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!open || !selectedDateEt || !metric) return;
    setLoading(true);
    setError("");
    try {
      const res = await getVeewashStep1Drilldown({
        date: selectedDateEt,
        metric,
        service: serviceFilter,
        rush: rushFilter,
      });
      setBags(res?.data?.bags || []);
    } catch (e) {
      setError(e?.response?.data?.error || e?.message || "Failed to load drill-down");
      setBags([]);
    } finally {
      setLoading(false);
    }
  }, [open, selectedDateEt, metric, serviceFilter, rushFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const startAction = (bag, action) => {
    setActionBag(bag.bag_id);
    setForm({
      action,
      bag_id: bag.bag_id,
      selected_date_et: selectedDateEt,
      reason: "",
      employee: bag.completed_by || "",
      completion_at: bag.completion_at ? String(bag.completion_at).slice(0, 16) : "",
      entry_at: "",
      service_type: bag.service_type || "WF",
      weight_lbs: "",
      weight_at: "",
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
        weight_at: form.weight_at ? form.weight_at.replace(" ", "T") : undefined,
        weight_lbs: form.weight_lbs !== "" ? Number(form.weight_lbs) : undefined,
      };
      const res = await postVeewashStep1Correction(body);
      if (!res?.data?.ok) {
        setError(res?.data?.error || "Correction failed");
        return;
      }
      setActionBag(null);
      await load();
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
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <Stack spacing={1}>
          <Typography variant="body2" color="text.secondary">
            {bags.length} bag{bags.length === 1 ? "" : "s"}
          </Typography>
          {bags.map((bag) => {
            const openRow = expanded === bag.bag_id;
            return (
              <Accordion
                key={bag.bag_id}
                expanded={openRow}
                onChange={() => setExpanded(openRow ? null : bag.bag_id)}
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
                      <Chip size="small" label={bag.dashboard_status || "—"} color="warning" variant="outlined" />
                    </Stack>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {bag.customer_name || "—"} · {bag.entry_class || "—"} · wt {bag.weight_lbs ?? "—"}
                    </Typography>
                    {(bag.reason_codes || []).length > 0 ? (
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                        {(bag.reason_codes || []).map((c) => (
                          <Chip key={c} size="small" label={REASON_LABELS[c] || c} sx={{ height: 20, fontSize: "0.68rem" }} />
                        ))}
                      </Stack>
                    ) : null}
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>
                    Entry: {bag.entry_source || "—"} @ {fmtTs(bag.entry_at)} · Completion: {fmtTs(bag.completion_at)} by{" "}
                    {bag.completed_by || "—"} · Portal: {bag.portal_status || "—"} · Last seen: {fmtTs(bag.last_seen_at)}
                  </Typography>
                  <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1, mb: 0.5 }}>
                    Scan chronology (ET)
                  </Typography>
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
                          <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtTs(s.scanned_at_parsed)}</TableCell>
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

                  <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1.5, mb: 0.5 }}>
                    System result
                  </Typography>
                  <Typography variant="caption" display="block">
                    Outcome {bag.system_result?.outcome || "—"} · Canonical {bag.system_result?.canonical_status || "—"} ·
                    Reasons {(bag.system_result?.reason_codes || []).join(", ") || "—"}
                  </Typography>
                  {(bag.corrections || []).length > 0 ? (
                    <>
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1, mb: 0.5 }}>
                        Manager corrections
                      </Typography>
                      {(bag.corrections || []).slice(0, 5).map((c, i) => (
                        <Typography key={i} variant="caption" display="block">
                          {fmtTs(c.created_at)} · {c.action} · {c.actor_display_name || "—"} · {c.reason_text}
                        </Typography>
                      ))}
                    </>
                  ) : null}

                  <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
                    <Button size="small" variant="outlined" onClick={() => startAction(bag, "mark_completed")}>
                      Mark completed
                    </Button>
                    <Button size="small" variant="outlined" onClick={() => startAction(bag, "return_pending")}>
                      Return to pending
                    </Button>
                    <Button size="small" variant="outlined" onClick={() => startAction(bag, "correct_entry")}>
                      Correct entry
                    </Button>
                    <Button size="small" variant="outlined" onClick={() => startAction(bag, "correct_weight")}>
                      Correct weight
                    </Button>
                    <Button size="small" color="error" variant="outlined" onClick={() => startAction(bag, "exclude")}>
                      Exclude
                    </Button>
                  </Stack>

                  {actionBag === bag.bag_id ? (
                    <Box sx={{ mt: 1.5, p: 1.25, bgcolor: VEEWASH_DASHBOARD.primaryBlueLight, borderRadius: 1 }}>
                      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
                        {form.action}
                      </Typography>
                      <Stack spacing={1}>
                        {(form.action === "mark_completed" || form.action === "correct_completion") && (
                          <>
                            <TextField
                              size="small"
                              label="Completed by"
                              value={form.employee || ""}
                              onChange={(e) => setForm((f) => ({ ...f, employee: e.target.value }))}
                            />
                            <TextField
                              size="small"
                              label="Completion (YYYY-MM-DDTHH:MM)"
                              value={form.completion_at || ""}
                              onChange={(e) => setForm((f) => ({ ...f, completion_at: e.target.value }))}
                            />
                          </>
                        )}
                        {form.action === "correct_entry" && (
                          <>
                            <FormControl size="small">
                              <InputLabel>Service</InputLabel>
                              <Select
                                label="Service"
                                value={form.service_type || "WF"}
                                onChange={(e) => setForm((f) => ({ ...f, service_type: e.target.value }))}
                              >
                                <MenuItem value="WF">WF</MenuItem>
                                <MenuItem value="HD">HD</MenuItem>
                              </Select>
                            </FormControl>
                            <TextField
                              size="small"
                              label="Entry at (YYYY-MM-DDTHH:MM)"
                              value={form.entry_at || ""}
                              onChange={(e) => setForm((f) => ({ ...f, entry_at: e.target.value }))}
                            />
                          </>
                        )}
                        {form.action === "correct_weight" && (
                          <>
                            <TextField
                              size="small"
                              type="number"
                              label="Weight lbs (>0)"
                              value={form.weight_lbs}
                              onChange={(e) => setForm((f) => ({ ...f, weight_lbs: e.target.value }))}
                            />
                            <TextField
                              size="small"
                              label="Weight at (YYYY-MM-DDTHH:MM)"
                              value={form.weight_at || ""}
                              onChange={(e) => setForm((f) => ({ ...f, weight_at: e.target.value }))}
                            />
                            <TextField
                              size="small"
                              label="Employee"
                              value={form.employee || ""}
                              onChange={(e) => setForm((f) => ({ ...f, employee: e.target.value }))}
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
        </Stack>
      )}
    </Drawer>
  );
}
