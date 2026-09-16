import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import QrCodeScannerIcon from "@mui/icons-material/QrCodeScanner";
import { useNavigate } from "react-router-dom";
import { Html5Qrcode } from "html5-qrcode";
import {
  createManagementIssue,
  getManagementIssuesOrderContext,
  getManagementIssuesTaxonomy,
  searchManagementIssuesBags,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { displayIdCollides } from "../utils/orderDisplayId";
import { IssuesPageShell } from "../components/management/issues/ManagementIssuesSubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const CATEGORY_CHIPS = [
  { code: "MISSING", label: "Missing" },
  { code: "DAMAGE", label: "Damage" },
  { code: "RECLEAN", label: "Reclean" },
  { code: "MIXED_CUSTOMER_ITEMS", label: "Mixed Items" },
  { code: "REJECTED", label: "Rejected" },
  { code: "FOUND", label: "Found" },
  { code: "QUALITY", label: "Quality" },
  { code: "OTHER", label: "Other" },
];

function todayEtLocal() {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function ChipButton({ selected, children, onClick }) {
  return (
    <Button
      onClick={onClick}
      sx={{
        textTransform: "none",
        fontWeight: selected ? 800 : 600,
        minHeight: 52,
        px: 1.5,
        borderRadius: 2,
        border: "1px solid",
        borderColor: selected
          ? VEEWASH_DASHBOARD.primaryBlue
          : "#e2e8f0",
        bgcolor: selected ? VEEWASH_DASHBOARD.primaryBlueLight : "#fff",
        color: selected
          ? VEEWASH_DASHBOARD.primaryBlueDark
          : "#334155",
        flex: "1 1 42%",
      }}
    >
      {children}
    </Button>
  );
}

export default function ManagementIssuesNewPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [q, setQ] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [context, setContext] = useState(null);
  const [unmatched, setUnmatched] = useState(false);
  const [manualId, setManualId] = useState("");
  const [unmatchedReason, setUnmatchedReason] = useState("");
  const [taxonomy, setTaxonomy] = useState({ categories: [], subtypes: [] });
  const [category, setCategory] = useState("");
  const [subtype, setSubtype] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [reportedDate, setReportedDate] = useState(todayEtLocal());
  const [attrEdits, setAttrEdits] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [scanOpen, setScanOpen] = useState(false);
  const scanRef = useRef(null);
  const html5Ref = useRef(null);

  useEffect(() => {
    getManagementIssuesTaxonomy()
      .then(({ data }) => setTaxonomy(data || { categories: [], subtypes: [] }))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (unmatched || !q.trim()) {
      setResults([]);
      return undefined;
    }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const { data } = await searchManagementIssuesBags(q.trim());
        setResults(data?.results || []);
      } catch (e) {
        setError(e?.response?.data?.error || e.message);
      } finally {
        setSearching(false);
      }
    }, 220);
    return () => clearTimeout(t);
  }, [q, unmatched]);

  const subtypes = useMemo(
    () =>
      (taxonomy.subtypes || []).filter(
        (s) => s.parent_category_code === category
      ),
    [taxonomy, category]
  );

  const selectResult = async (row) => {
    setError("");
    setSelected(row);
    setUnmatched(false);
    setSearching(true);
    try {
      const { data } = await getManagementIssuesOrderContext(
        row.bag_id,
        row.order_instance_id
      );
      setContext(data);
      const edits = {};
      (data.attribution_candidates || []).forEach((c) => {
        edits[c.role_key] = {
          role_key: c.role_key,
          employee_name: c.employee_name,
          employee_user_id: c.employee_user_id,
          confirm: false,
          change: false,
          is_primary: !!c.is_primary_candidate,
          reason: "",
        };
      });
      setAttrEdits(edits);
      setStep(2);
    } catch (e) {
      setError(e?.response?.data?.error || e.message);
    } finally {
      setSearching(false);
    }
  };

  const startScan = useCallback(async () => {
    setScanOpen(true);
    setTimeout(async () => {
      try {
        const elId = "mgmt-issues-qr-reader";
        const scanner = new Html5Qrcode(elId);
        html5Ref.current = scanner;
        await scanner.start(
          { facingMode: "environment" },
          { fps: 8, qrbox: { width: 220, height: 220 } },
          (decoded) => {
            const text = String(decoded || "").trim();
            if (text) {
              setQ(text);
              setScanOpen(false);
              scanner.stop().catch(() => {});
              html5Ref.current = null;
            }
          },
          () => {}
        );
      } catch {
        setError("Camera scan unavailable — paste or type Bag ID");
        setScanOpen(false);
      }
    }, 200);
  }, []);

  useEffect(() => {
    if (!scanOpen && html5Ref.current) {
      html5Ref.current.stop().catch(() => {});
      html5Ref.current = null;
    }
  }, [scanOpen]);

  const save = async () => {
    setError("");
    if (!unmatched && !selected?.order_instance_id) {
      setError("selection_required");
      return;
    }
    if (!category || !subtype) {
      setError("Choose issue category and subtype");
      return;
    }
    for (const ed of Object.values(attrEdits)) {
      if ((ed.change || ed.not_applicable) && !String(ed.reason || "").trim()) {
        setError("Override reason required when changing attribution");
        return;
      }
    }
    setSaving(true);
    try {
      const body = unmatched
        ? {
            matched_state: "UNMATCHED",
            unmatched: true,
            manual_identifier: manualId,
            unmatched_reason: unmatchedReason,
            issue_category: category,
            issue_subtype: subtype,
            description,
            internal_notes: notes,
            reported_at_et: `${reportedDate}T12:00:00`,
          }
        : {
            matched_state: "MATCHED",
            selected: true,
            selection_token: `${selected.bag_id}:${selected.order_instance_id}`,
            bag_id: selected.bag_id,
            order_instance_id: selected.order_instance_id,
            issue_category: category,
            issue_subtype: subtype,
            description,
            internal_notes: notes,
            reported_at_et: `${reportedDate}T12:00:00`,
            attributions: Object.values(attrEdits),
          };
      const { data } = await createManagementIssue(body);
      const id = data?.issue?.id;
      navigate(id ? `/management/issues/${id}` : "/management/issues");
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <ManagementHubNav activeId="issues" />
      <IssuesPageShell title="New Issue" showSubNav={false}>
        {error ? (
          <Alert severity="error" sx={{ mb: 1.5 }}>
            {error}
          </Alert>
        ) : null}

        {step === 1 || (!context && !unmatched) ? (
          <Box>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>Find Bag</Typography>
            <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
              <TextField
                fullWidth
                placeholder="Scan / Search Bag ID"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setSelected(null);
                  setContext(null);
                }}
                inputProps={{ style: { fontSize: 16 } }}
                sx={{ bgcolor: "#fff" }}
              />
              <Button
                variant="outlined"
                onClick={startScan}
                sx={{ minWidth: 52, minHeight: 52 }}
                aria-label="Scan"
              >
                <QrCodeScannerIcon />
              </Button>
            </Stack>
            {searching ? <CircularProgress size={22} sx={{ mb: 1 }} /> : null}
            <Stack spacing={1}>
              {results.map((r) => (
                <Box
                  key={`${r.bag_id}-${r.order_instance_id}`}
                  sx={{
                    bgcolor: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 2,
                    p: 1.5,
                  }}
                >
                  <Typography sx={{ fontWeight: 900, fontSize: 16 }}>
                    {r.order_display_id || r.bag_id}
                  </Typography>
                  <Typography sx={{ fontSize: 14 }}>
                    {r.customer_name || "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 13, color: "#64748b" }}>
                    {r.service_type} · {r.rush ? "Rush" : "Non-Rush"}
                    {displayIdCollides(r, results) ? ` · OI ${r.order_instance_id}` : ""}
                    {r.production_date_et ? ` · ${r.production_date_et}` : ""}
                  </Typography>
                  <Button
                    fullWidth
                    variant="contained"
                    onClick={() => selectResult(r)}
                    sx={{
                      mt: 1,
                      minHeight: 44,
                      textTransform: "none",
                      fontWeight: 800,
                      bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                    }}
                  >
                    Select
                  </Button>
                </Box>
              ))}
            </Stack>
            <Button
              fullWidth
              onClick={() => {
                setUnmatched(true);
                setSelected(null);
                setContext(null);
                setStep(3);
              }}
              sx={{
                mt: 2,
                minHeight: 48,
                textTransform: "none",
                color: "#92400e",
                fontWeight: 700,
              }}
            >
              Bag / Order Not Found
            </Button>
          </Box>
        ) : null}

        {context && !unmatched ? (
          <Box sx={{ mb: 2 }}>
            <Typography
              sx={{
                fontSize: 11,
                fontWeight: 800,
                letterSpacing: 0.8,
                color: "#64748b",
              }}
            >
              SELECTED ORDER
            </Typography>
            <Box
              sx={{
                bgcolor: "#fff",
                border: `1px solid ${VEEWASH_DASHBOARD.primaryBlueBorder}`,
                borderRadius: 2,
                p: 1.5,
                mt: 0.5,
              }}
            >
              <Typography sx={{ fontWeight: 900, fontSize: 18 }}>
                {context.order_display_id || context.bag_id}
              </Typography>
              <Typography>{context.customer_name || "—"}</Typography>
              <Typography sx={{ fontSize: 13, color: "#64748b" }}>
                {context.service_type} · {context.rush ? "Rush" : "Non-Rush"} ·
                OI {context.order_instance_id}
              </Typography>
              <Stack direction="row" spacing={3} sx={{ mt: 1 }}>
                <Box>
                  <Typography sx={{ fontSize: 11, color: "#94a3b8" }}>
                    PRE
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>
                    {context.pre_lbs != null ? `${context.pre_lbs} lb` : "—"}
                  </Typography>
                </Box>
                <Box>
                  <Typography sx={{ fontSize: 11, color: "#94a3b8" }}>
                    POST
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>
                    {context.post_lbs != null ? `${context.post_lbs} lb` : "—"}
                  </Typography>
                </Box>
              </Stack>
              <Typography sx={{ fontSize: 13, mt: 1 }}>
                Completed {context.completed_at_et || "—"}
              </Typography>
              {context.folder_employee_name ? (
                <Typography sx={{ fontSize: 13 }}>
                  Folder · {context.folder_employee_name}
                </Typography>
              ) : null}
              <Button
                onClick={() => {
                  setContext(null);
                  setSelected(null);
                  setStep(1);
                }}
                sx={{ mt: 1, textTransform: "none", fontWeight: 700 }}
              >
                Change Bag
              </Button>
            </Box>
          </Box>
        ) : null}

        {unmatched ? (
          <Box sx={{ mb: 2 }}>
            <Chip label="UNMATCHED" color="warning" sx={{ mb: 1, fontWeight: 800 }} />
            <TextField
              fullWidth
              label="Manual identifier"
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              sx={{ mb: 1, bgcolor: "#fff" }}
              inputProps={{ style: { fontSize: 16 } }}
            />
            <TextField
              fullWidth
              label="Why no canonical bag?"
              value={unmatchedReason}
              onChange={(e) => setUnmatchedReason(e.target.value)}
              multiline
              minRows={2}
              sx={{ bgcolor: "#fff" }}
              inputProps={{ style: { fontSize: 16 } }}
            />
            <Button
              onClick={() => {
                setUnmatched(false);
                setStep(1);
              }}
              sx={{ mt: 1, textTransform: "none" }}
            >
              Back to search
            </Button>
          </Box>
        ) : null}

        {(context || unmatched) && (
          <>
            <Typography sx={{ fontWeight: 800, mb: 1 }}>
              What happened?
            </Typography>
            <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 2 }}>
              {CATEGORY_CHIPS.map((c) => (
                <ChipButton
                  key={c.code}
                  selected={category === c.code}
                  onClick={() => {
                    setCategory(c.code);
                    setSubtype("");
                  }}
                >
                  {c.label}
                </ChipButton>
              ))}
            </Stack>

            {category ? (
              <>
                <Typography sx={{ fontWeight: 700, mb: 1, fontSize: 14 }}>
                  Subtype
                </Typography>
                <Stack
                  direction="row"
                  flexWrap="wrap"
                  useFlexGap
                  spacing={1}
                  sx={{ mb: 2 }}
                >
                  {subtypes.map((s) => (
                    <ChipButton
                      key={s.code}
                      selected={subtype === s.code}
                      onClick={() => setSubtype(s.code)}
                    >
                      {s.label}
                    </ChipButton>
                  ))}
                </Stack>
              </>
            ) : null}

            <TextField
              fullWidth
              label="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              multiline
              minRows={2}
              sx={{ mb: 1, bgcolor: "#fff" }}
              inputProps={{ style: { fontSize: 16 } }}
            />
            <TextField
              fullWidth
              label="Internal notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              multiline
              minRows={2}
              sx={{ mb: 1, bgcolor: "#fff" }}
              inputProps={{ style: { fontSize: 16 } }}
            />
            <TextField
              fullWidth
              type="date"
              label="Reported date (ET)"
              value={reportedDate}
              onChange={(e) => setReportedDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              sx={{ mb: 2, bgcolor: "#fff" }}
              inputProps={{ style: { fontSize: 16 } }}
            />

            {context && (context.attribution_candidates || []).length > 0 ? (
              <Box sx={{ mb: 2 }}>
                <Typography sx={{ fontWeight: 800, mb: 0.5 }}>
                  Production attribution
                </Typography>
                <Typography sx={{ fontSize: 12, color: "#64748b", mb: 1 }}>
                  Shown for context — not automatic fault.
                </Typography>
                <Stack spacing={1}>
                  {(context.attribution_candidates || []).map((c) => {
                    const ed = attrEdits[c.role_key] || {};
                    return (
                      <Box
                        key={c.role_key}
                        sx={{
                          bgcolor: "#fff",
                          border: "1px solid #e5e7eb",
                          borderRadius: 2,
                          p: 1.25,
                        }}
                      >
                        <Typography sx={{ fontWeight: 800, fontSize: 13 }}>
                          {c.role_key}
                        </Typography>
                        <Typography sx={{ fontSize: 15 }}>
                          {ed.employee_name || c.employee_name || "—"}
                        </Typography>
                        <Typography sx={{ fontSize: 12, color: "#94a3b8" }}>
                          Auto · {c.confidence} confidence
                        </Typography>
                        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                          <Button
                            size="small"
                            variant={ed.confirm && !ed.change ? "contained" : "outlined"}
                            onClick={() =>
                              setAttrEdits((prev) => ({
                                ...prev,
                                [c.role_key]: {
                                  ...prev[c.role_key],
                                  confirm: true,
                                  change: false,
                                  employee_name: c.employee_name,
                                },
                              }))
                            }
                            sx={{ textTransform: "none", minHeight: 40 }}
                          >
                            Confirm
                          </Button>
                          <Button
                            size="small"
                            onClick={() => {
                              const name = window.prompt(
                                "Employee name",
                                ed.employee_name || c.employee_name || ""
                              );
                              if (name == null) return;
                              const reason = window.prompt(
                                "Reason for change (required)"
                              );
                              if (!reason) return;
                              setAttrEdits((prev) => ({
                                ...prev,
                                [c.role_key]: {
                                  ...prev[c.role_key],
                                  confirm: true,
                                  change: true,
                                  employee_name: name,
                                  reason,
                                },
                              }));
                            }}
                            sx={{ textTransform: "none", minHeight: 40 }}
                          >
                            Change
                          </Button>
                        </Stack>
                      </Box>
                    );
                  })}
                </Stack>
              </Box>
            ) : null}

            <Button
              fullWidth
              variant="contained"
              disabled={saving}
              onClick={save}
              sx={{
                minHeight: 52,
                textTransform: "none",
                fontWeight: 900,
                fontSize: 16,
                bgcolor: VEEWASH_DASHBOARD.primaryBlue,
              }}
            >
              {saving ? "Saving…" : "Save Issue"}
            </Button>
          </>
        )}

        <Dialog open={scanOpen} onClose={() => setScanOpen(false)} fullWidth>
          <DialogTitle>Scan Bag QR</DialogTitle>
          <DialogContent>
            <Box id="mgmt-issues-qr-reader" ref={scanRef} sx={{ width: "100%" }} />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setScanOpen(false)}>Close</Button>
          </DialogActions>
        </Dialog>
      </IssuesPageShell>
    </>
  );
}
