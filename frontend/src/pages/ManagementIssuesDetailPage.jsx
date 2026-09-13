import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useNavigate, useParams } from "react-router-dom";
import {
  getManagementIssue,
  getManagementIssuesOrderContext,
  linkManagementIssueBag,
  patchManagementIssue,
  putManagementIssueAttributions,
  searchManagementIssuesBags,
} from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { IssuesPageShell } from "../components/management/issues/ManagementIssuesSubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

export default function ManagementIssuesDetailPage() {
  const { issueId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [claim, setClaim] = useState("");
  const [vendorPct, setVendorPct] = useState("");
  const [finalClaim, setFinalClaim] = useState("");
  const [resolutionType, setResolutionType] = useState("");
  const [resolutionNotes, setResolutionNotes] = useState("");
  const [linkQ, setLinkQ] = useState("");
  const [linkResults, setLinkResults] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data: payload } = await getManagementIssue(issueId, {
        events: 1,
      });
      setData(payload);
      const iss = payload?.issue || {};
      setClaim(iss.claim_amount != null ? String(iss.claim_amount) : "");
      setVendorPct(
        iss.vendor_percentage != null ? String(iss.vendor_percentage) : ""
      );
      setFinalClaim(
        iss.final_vendor_claim != null ? String(iss.final_vendor_claim) : ""
      );
      setResolutionType(iss.resolution_type || "");
      setResolutionNotes(iss.resolution_notes || "");
    } catch (e) {
      setError(e?.response?.data?.error || e.message);
    } finally {
      setLoading(false);
    }
  }, [issueId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!linkQ.trim()) {
      setLinkResults([]);
      return undefined;
    }
    const t = setTimeout(async () => {
      try {
        const { data: res } = await searchManagementIssuesBags(linkQ.trim());
        setLinkResults(res?.results || []);
      } catch {
        setLinkResults([]);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [linkQ]);

  const iss = data?.issue;
  const attrs = data?.attributions || [];
  const events = data?.events || [];

  const patch = async (body) => {
    setBusy(true);
    setError("");
    try {
      const { data: payload } = await patchManagementIssue(issueId, body);
      setData((prev) => ({ ...prev, ...payload }));
      await load();
    } catch (e) {
      setError(e?.response?.data?.error || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <>
        <ManagementHubNav activeId="issues" />
        <Box sx={{ py: 6, textAlign: "center" }}>
          <CircularProgress />
        </Box>
      </>
    );
  }

  if (!iss) {
    return (
      <>
        <ManagementHubNav activeId="issues" />
        <IssuesPageShell title="Issue">
          <Alert severity="error">{error || "Not found"}</Alert>
        </IssuesPageShell>
      </>
    );
  }

  return (
    <>
      <ManagementHubNav activeId="issues" />
      <IssuesPageShell title={`Issue #${iss.id}`}>
        {error ? (
          <Alert severity="error" sx={{ mb: 1 }}>
            {error}
          </Alert>
        ) : null}

        <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: "wrap" }}>
          <Chip label={iss.status} sx={{ fontWeight: 700 }} />
          <Chip
            label={iss.matched_state}
            color={iss.matched_state === "UNMATCHED" ? "warning" : "default"}
          />
          <Chip label={`${iss.issue_category} / ${iss.issue_subtype}`} />
        </Stack>

        <Box
          sx={{
            bgcolor: "#fff",
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            p: 1.5,
            mb: 1.5,
          }}
        >
          <Typography sx={{ fontWeight: 800, mb: 0.5 }}>Order</Typography>
          <Typography sx={{ fontWeight: 900, fontSize: 18 }}>
            {iss.bag_id || iss.manual_identifier || "—"}
          </Typography>
          <Typography>{iss.customer_name_snapshot || "—"}</Typography>
          <Typography sx={{ fontSize: 13, color: "#64748b" }}>
            {iss.service_type_snapshot || "—"} · OI{" "}
            {iss.order_instance_id || "—"} · Prod {iss.production_date_et || "—"}
          </Typography>
          {iss.matched_state === "UNMATCHED" ? (
            <Typography sx={{ fontSize: 13, mt: 0.5 }}>
              Reason: {iss.unmatched_reason}
            </Typography>
          ) : null}
        </Box>

        <Box
          sx={{
            bgcolor: "#fff",
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            p: 1.5,
            mb: 1.5,
          }}
        >
          <Typography sx={{ fontWeight: 800 }}>Details</Typography>
          <Typography sx={{ whiteSpace: "pre-wrap", mt: 0.5 }}>
            {iss.description || "—"}
          </Typography>
          {iss.internal_notes ? (
            <Typography sx={{ fontSize: 13, color: "#64748b", mt: 1 }}>
              Internal: {iss.internal_notes}
            </Typography>
          ) : null}
          <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 1 }}>
            Reported {iss.reported_at_et}
          </Typography>
        </Box>

        <Box
          sx={{
            bgcolor: "#fff",
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            p: 1.5,
            mb: 1.5,
          }}
        >
          <Typography sx={{ fontWeight: 800, mb: 1 }}>
            Production attribution
          </Typography>
          {attrs.length === 0 ? (
            <Typography color="text.secondary">None</Typography>
          ) : (
            <Stack spacing={1}>
              {attrs.map((a) => (
                <Box key={a.id}>
                  <Typography sx={{ fontWeight: 700 }}>
                    {a.role_key}
                    {a.is_primary ? " · Primary" : ""}
                  </Typography>
                  <Typography>
                    {a.is_not_applicable
                      ? "Not applicable"
                      : a.employee_name_snapshot || "—"}
                  </Typography>
                  <Typography sx={{ fontSize: 12, color: "#94a3b8" }}>
                    {a.attribution_source} · {a.confidence}
                    {a.is_manager_override ? " · override" : ""}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
          <Button
            sx={{ mt: 1, textTransform: "none", minHeight: 40 }}
            disabled={busy}
            onClick={async () => {
              const name = window.prompt("Primary employee name");
              if (!name) return;
              const reason = window.prompt("Reason (required)");
              if (!reason) return;
              setBusy(true);
              try {
                await putManagementIssueAttributions(issueId, {
                  reason,
                  attributions: [
                    {
                      role_key: "folder",
                      stage_key: "folder",
                      employee_name: name,
                      is_primary: true,
                      reason,
                    },
                  ],
                });
                await load();
              } catch (e) {
                setError(e?.response?.data?.error || e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Change attribution
          </Button>
        </Box>

        <Box
          sx={{
            bgcolor: "#fff",
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            p: 1.5,
            mb: 1.5,
          }}
        >
          <Typography sx={{ fontWeight: 800, mb: 1 }}>
            Resolution / Financial
          </Typography>
          <TextField
            select
            fullWidth
            size="small"
            label="Status"
            value={iss.status}
            onChange={(e) => patch({ status: e.target.value })}
            sx={{ mb: 1 }}
          >
            {["open", "investigating", "resolved", "excluded"].map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            fullWidth
            size="small"
            label="Resolution type"
            value={resolutionType}
            onChange={(e) => setResolutionType(e.target.value)}
            sx={{ mb: 1 }}
          />
          <TextField
            fullWidth
            size="small"
            label="Resolution notes"
            value={resolutionNotes}
            onChange={(e) => setResolutionNotes(e.target.value)}
            sx={{ mb: 1 }}
          />
          <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
            <TextField
              size="small"
              label="Claim $"
              value={claim}
              onChange={(e) => setClaim(e.target.value)}
            />
            <TextField
              size="small"
              label="Vendor %"
              value={vendorPct}
              onChange={(e) => setVendorPct(e.target.value)}
            />
            <TextField
              size="small"
              label="Final $"
              value={finalClaim}
              onChange={(e) => setFinalClaim(e.target.value)}
            />
          </Stack>
          <Button
            variant="contained"
            disabled={busy}
            onClick={() =>
              patch({
                resolution_type: resolutionType || undefined,
                resolution_notes: resolutionNotes || undefined,
                claim_amount: claim === "" ? null : claim,
                vendor_percentage: vendorPct === "" ? null : vendorPct,
                final_vendor_claim: finalClaim === "" ? null : finalClaim,
                status: iss.status === "open" ? "resolved" : iss.status,
              })
            }
            sx={{
              textTransform: "none",
              fontWeight: 800,
              minHeight: 44,
              bgcolor: VEEWASH_DASHBOARD.teal,
            }}
          >
            Save resolution / $
          </Button>
        </Box>

        {iss.matched_state === "UNMATCHED" ? (
          <Box
            sx={{
              bgcolor: "#fff",
              borderRadius: 2,
              border: "1px solid #fbbf24",
              p: 1.5,
              mb: 1.5,
            }}
          >
            <Typography sx={{ fontWeight: 800, mb: 1 }}>Link to Bag</Typography>
            <TextField
              fullWidth
              size="small"
              placeholder="Search bag / OI"
              value={linkQ}
              onChange={(e) => setLinkQ(e.target.value)}
              sx={{ mb: 1 }}
              inputProps={{ style: { fontSize: 16 } }}
            />
            <Stack spacing={1}>
              {linkResults.map((r) => (
                <Button
                  key={`${r.bag_id}-${r.order_instance_id}`}
                  variant="outlined"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await getManagementIssuesOrderContext(
                        r.bag_id,
                        r.order_instance_id
                      );
                      await linkManagementIssueBag(issueId, {
                        bag_id: r.bag_id,
                        order_instance_id: r.order_instance_id,
                      });
                      await load();
                      setLinkQ("");
                    } catch (e) {
                      setError(e?.response?.data?.error || e.message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                  sx={{
                    textTransform: "none",
                    justifyContent: "flex-start",
                    minHeight: 48,
                  }}
                >
                  {r.bag_id} · OI {r.order_instance_id} ·{" "}
                  {r.customer_name || ""}
                </Button>
              ))}
            </Stack>
          </Box>
        ) : null}

        <Box
          sx={{
            bgcolor: "#fff",
            borderRadius: 2,
            border: "1px solid #e5e7eb",
            p: 1.5,
          }}
        >
          <Typography sx={{ fontWeight: 800, mb: 1 }}>History</Typography>
          <Stack spacing={0.75}>
            {events.map((ev) => (
              <Typography key={ev.id} sx={{ fontSize: 13 }}>
                <strong>{ev.action}</strong> · {ev.actor_display_name || "—"} ·{" "}
                {ev.created_at}
                {ev.reason ? ` · ${ev.reason}` : ""}
              </Typography>
            ))}
            {events.length === 0 ? (
              <Typography color="text.secondary">No events</Typography>
            ) : null}
          </Stack>
        </Box>

        <Button
          onClick={() => navigate("/management/issues")}
          sx={{ mt: 2, textTransform: "none" }}
        >
          Back to list
        </Button>
      </IssuesPageShell>
    </>
  );
}
