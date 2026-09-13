import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import { getManagementIssues } from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { IssuesPageShell } from "../components/management/issues/ManagementIssuesSubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const STATUS_COLORS = {
  open: VEEWASH_DASHBOARD.pending,
  investigating: VEEWASH_DASHBOARD.primaryBlue,
  resolved: VEEWASH_DASHBOARD.teal,
  excluded: "#64748b",
};

export default function ManagementIssuesPage() {
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState([]);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState(searchParams.get("category") || "");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await getManagementIssues({
        status: status || undefined,
        category: category || undefined,
        q: q || undefined,
        limit: 50,
      });
      setIssues(data?.issues || []);
    } catch (e) {
      setError(e?.response?.data?.error || e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [status, category, q]);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  return (
    <>
      <ManagementHubNav activeId="issues" />
      <IssuesPageShell title="Issues">
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          sx={{ mb: 1.5 }}
        >
          <TextField
            size="small"
            label="Search bag / customer / #"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            fullWidth
            inputProps={{ style: { fontSize: 16 } }}
            sx={{ bgcolor: "#fff" }}
          />
          <TextField
            select
            size="small"
            label="Status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            sx={{ minWidth: 140, bgcolor: "#fff" }}
          >
            <MenuItem value="">All</MenuItem>
            <MenuItem value="open">Open</MenuItem>
            <MenuItem value="investigating">Investigating</MenuItem>
            <MenuItem value="resolved">Resolved</MenuItem>
            <MenuItem value="excluded">Excluded</MenuItem>
          </TextField>
          <TextField
            select
            size="small"
            label="Type"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            sx={{ minWidth: 140, bgcolor: "#fff" }}
          >
            <MenuItem value="">All</MenuItem>
            {[
              "MISSING",
              "DAMAGE",
              "RECLEAN",
              "MIXED_CUSTOMER_ITEMS",
              "REJECTED",
              "FOUND",
              "QUALITY",
              "OTHER",
            ].map((c) => (
              <MenuItem key={c} value={c}>
                {c}
              </MenuItem>
            ))}
          </TextField>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}
        {loading ? (
          <Box sx={{ py: 4, textAlign: "center" }}>
            <CircularProgress size={28} />
          </Box>
        ) : issues.length === 0 ? (
          <Typography color="text.secondary" sx={{ py: 3 }}>
            No issues yet. Tap + New Issue to create one.
          </Typography>
        ) : (
          <Stack spacing={1}>
            {issues.map((iss) => (
              <Box
                key={iss.id}
                component={RouterLink}
                to={`/management/issues/${iss.id}`}
                sx={{
                  display: "block",
                  textDecoration: "none",
                  color: "inherit",
                  bgcolor: "#fff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 2,
                  p: 1.5,
                  minHeight: 72,
                  boxShadow: VEEWASH_DASHBOARD.cardShadow,
                }}
              >
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="flex-start"
                  gap={1}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 800, fontSize: 15 }}>
                      #{iss.id}{" "}
                      {iss.bag_id || iss.manual_identifier || "Unmatched"}
                    </Typography>
                    <Typography
                      sx={{ fontSize: 13, color: "#64748b" }}
                      noWrap
                    >
                      {iss.customer_name_snapshot || "—"} ·{" "}
                      {iss.issue_category}
                      {iss.issue_subtype ? ` / ${iss.issue_subtype}` : ""}
                    </Typography>
                    <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.25 }}>
                      Prod {iss.production_date_et || "—"} · Reported{" "}
                      {String(iss.reported_at_et || "").slice(0, 10)}
                      {iss.primary_employee_name
                        ? ` · ${iss.primary_employee_name}`
                        : ""}
                    </Typography>
                  </Box>
                  <Stack alignItems="flex-end" spacing={0.5}>
                    <Chip
                      size="small"
                      label={iss.status}
                      sx={{
                        fontWeight: 700,
                        bgcolor: `${STATUS_COLORS[iss.status] || "#94a3b8"}22`,
                        color: STATUS_COLORS[iss.status] || "#64748b",
                      }}
                    />
                    {iss.matched_state === "UNMATCHED" ? (
                      <Chip size="small" label="UNMATCHED" color="warning" />
                    ) : null}
                    {iss.claim_amount != null ? (
                      <Typography sx={{ fontSize: 12, fontWeight: 700 }}>
                        ${Number(iss.claim_amount).toFixed(2)}
                      </Typography>
                    ) : null}
                  </Stack>
                </Stack>
              </Box>
            ))}
          </Stack>
        )}
      </IssuesPageShell>
    </>
  );
}
