import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { getManagementRinseWfReviewDetail } from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import EditBagPanel from "../shift/EditBagPanel";

function fmtLbs(v) {
  if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} lb`;
}

function fmtTime(v) {
  if (!v) return "—";
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

function Section({ title, children }) {
  return (
    <Box sx={{ mb: 1.75 }}>
      <Typography
        sx={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: 0.7,
          textTransform: "uppercase",
          color: "#64748b",
          mb: 0.75,
        }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function KV({ label, value }) {
  return (
    <Stack direction="row" spacing={1} sx={{ mb: 0.35 }}>
      <Typography sx={{ fontSize: 12, color: "#64748b", minWidth: 110 }}>{label}</Typography>
      <Typography sx={{ fontSize: 13, fontWeight: 650, color: "#0f172a" }}>{value ?? "—"}</Typography>
    </Stack>
  );
}

/**
 * On-demand Review modal — fetches ONE bag detail (scans included) only when opened.
 * Weights come from the canonical resolver via the Management detail endpoint.
 */
export default function ManagementRinseWfReviewModal({
  open,
  bagId,
  selectedDateEt,
  readOnly = false,
  onClose,
  onSaved,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!open || !bagId || !selectedDateEt) {
      setDetail(null);
      setError("");
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      setDetail(null);
      try {
        const res = await getManagementRinseWfReviewDetail(selectedDateEt, bagId);
        if (cancelled) return;
        const data = res?.data || {};
        if (data.ok === false) {
          setError(data.message || data.error || "Failed to load detail");
          setDetail(null);
        } else {
          setDetail(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err?.response?.data?.error || err?.message || "Failed to load detail");
          setDetail(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, bagId, selectedDateEt]);

  const bag = detail?.bag || null;
  const weights = bag?.weights || {};
  const scans = Array.isArray(bag?.scans) ? bag.scans : [];
  const catalog = Array.isArray(detail?.active_bulk_workitems)
    ? detail.active_bulk_workitems
    : [];

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" scroll="paper">
      <DialogTitle sx={{ pb: 0.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: 17 }}>
              {bag?.customer_name || bagId || "Review"}
            </Typography>
            <Typography sx={{ fontSize: 13, color: "#64748b" }}>{bagId}</Typography>
          </Box>
          <Button onClick={onClose} sx={{ textTransform: "none" }}>
            Close
          </Button>
        </Stack>
      </DialogTitle>
      <DialogContent dividers>
        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
            <CircularProgress size={32} />
          </Box>
        ) : error ? (
          <Alert severity="error">{error}</Alert>
        ) : !bag ? (
          <Typography sx={{ color: "#64748b" }}>No detail available.</Typography>
        ) : (
          <>
            <Section title="Order">
              <KV label="Customer" value={bag.customer_name} />
              <KV label="Bag / Order" value={bag.bag_id} />
              <KV label="Service" value={bag.service_type || "WF"} />
              <KV label="Business date" value={selectedDateEt} />
              <KV label="Rush" value={bag.rush_flag || "—"} />
              <KV label="Status" value={bag.dashboard_status || bag.outcome} />
              <KV label="Review category" value={bag.review_category_label} />
              <KV label="Review reason" value={bag.short_reason || (bag.reason_codes || []).join(", ")} />
            </Section>

            <Section title="Employee / Resource">
              <KV
                label="Employee"
                value={
                  bag.completed_by
                  || weights.pre_weight_employee
                  || weights.post_weight_employee
                  || "—"
                }
              />
              <KV label="PRE employee" value={weights.pre_weight_employee} />
              <KV label="POST employee" value={weights.post_weight_employee} />
            </Section>

            <Section title="Weights">
              <Alert severity="info" sx={{ mb: 1, py: 0.25 }}>
                Canonical WF weight resolver — Review does not reclassify PRE/POST.
              </Alert>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
                  gap: 1,
                }}
              >
                <Box sx={{ border: "1px solid #e2e8f0", borderRadius: 1, p: 1 }}>
                  <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b" }}>
                    PRE WEIGHT
                  </Typography>
                  <Typography sx={{ fontSize: 18, fontWeight: 800 }}>{fmtLbs(weights.pre_weight_lbs)}</Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>{fmtTime(weights.pre_weight_at)}</Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                    {weights.pre_weight_employee || "—"}
                  </Typography>
                </Box>
                <Box sx={{ border: "1px solid #e2e8f0", borderRadius: 1, p: 1 }}>
                  <Typography sx={{ fontSize: 11, fontWeight: 800, color: "#64748b" }}>
                    POST WEIGHT
                  </Typography>
                  <Typography sx={{ fontSize: 18, fontWeight: 800 }}>
                    {weights.post_weight_lbs != null ? fmtLbs(weights.post_weight_lbs) : "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>{fmtTime(weights.post_weight_at)}</Typography>
                  <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                    {weights.post_weight_employee || "—"}
                  </Typography>
                </Box>
              </Box>
            </Section>

            <Section title="Specialty Items">
              <KV
                label="Comforters"
                value={
                  bag.comforter_quantity != null ? String(bag.comforter_quantity) : "0"
                }
              />
              <KV
                label="Bath Mats"
                value={bag.bath_mat_quantity != null ? String(bag.bath_mat_quantity) : "0"}
              />
              {(bag.other_specialty_lines || []).map((line) => (
                <KV
                  key={`${line.name}-${line.quantity}`}
                  label={line.name}
                  value={String(line.quantity ?? "—")}
                />
              ))}
            </Section>

            <Section title="Quality">
              <KV
                label="Rejected"
                value={
                  bag.rejection_status
                  || (bag.create_issue_at ? "Yes" : "No")
                }
              />
              <KV
                label="Split"
                value={
                  bag.split_order || bag.split_confirmed
                    ? bag.split_status || "Yes"
                    : "No"
                }
              />
            </Section>

            {detail?.portal_evidence ? (
              <Section title="Portal / Evidence">
                <KV label="Portal status" value={detail.portal_evidence.portal_status} />
                <KV label="Last seen" value={fmtTime(detail.portal_evidence.last_seen_at)} />
                <Typography sx={{ fontSize: 12, color: "#475569", mt: 0.5 }}>
                  {detail.portal_evidence.explanation}
                </Typography>
              </Section>
            ) : null}

            <Section title="Scans">
              {scans.length === 0 ? (
                <Typography sx={{ fontSize: 13, color: "#64748b" }}>No scans loaded.</Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Time</TableCell>
                      <TableCell>Purpose</TableCell>
                      <TableCell>Employee</TableCell>
                      <TableCell>Resource</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {scans.map((scan, idx) => (
                      <TableRow key={scan.id || `${scan.scanned_at_parsed}-${idx}`}>
                        <TableCell sx={{ whiteSpace: "nowrap", fontSize: 12 }}>
                          {fmtTime(scan.scanned_at_parsed || scan.scanned_at)}
                        </TableCell>
                        <TableCell sx={{ fontSize: 12 }}>{scan.purpose || "—"}</TableCell>
                        <TableCell sx={{ fontSize: 12 }}>{scan.user_name || "—"}</TableCell>
                        <TableCell sx={{ fontSize: 12 }}>{scan.rack || scan.resource || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {detail?._meta?.elapsed_ms != null ? (
                <Typography sx={{ mt: 0.75, fontSize: 10, color: "#94a3b8" }}>
                  Detail {detail._meta.elapsed_ms} ms · scans{" "}
                  {detail._meta.scans_loaded ? "yes" : "no"}
                </Typography>
              ) : null}
            </Section>

            <Divider sx={{ my: 1.5 }} />

            <Section title="Review Action">
              {readOnly ? (
                <Alert severity="warning">Day is closed — review is read-only.</Alert>
              ) : (
                <EditBagPanel
                  bag={bag}
                  selectedDateEt={selectedDateEt}
                  catalog={catalog}
                  readOnly={readOnly}
                  onCancel={onClose}
                  onSaved={() => {
                    onSaved?.();
                    onClose?.();
                  }}
                />
              )}
            </Section>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
