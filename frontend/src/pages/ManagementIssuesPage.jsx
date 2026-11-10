import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Drawer,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getIssuesRegister, getLostFoundItem, getLostFoundPhoto, updateLostFoundStatus } from "../api";
import ManagementHubNav from "../components/management/ManagementHubNav";
import { IssuesPageShell } from "../components/management/issues/ManagementIssuesSubNav";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";
import { businessTodayYmd } from "../utils/businessTime";

const FOUND_STATUSES = ["new", "under_review", "returned", "stored", "resolved"];
const OTHER_STATUSES = ["new", "under_review", "resolved"];

function shiftDay(ymd, days) {
  const [year, month, day] = String(ymd).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function statusesFor(item) {
  return item?.report_category === "orphan" || !item?.report_category ? FOUND_STATUSES : OTHER_STATUSES;
}

function CountCard({ label, value, selected, onClick }) {
  return (
    <Button
      onClick={onClick}
      sx={{
        flex: "1 1 140px",
        minHeight: 72,
        justifyContent: "flex-start",
        textAlign: "left",
        textTransform: "none",
        bgcolor: "#fff",
        border: "1px solid",
        borderColor: selected ? VEEWASH_DASHBOARD.primaryBlue : "#e5e7eb",
        borderRadius: 2,
        px: 1.5,
      }}
    >
      <Box>
        <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 700 }}>{label}</Typography>
        <Typography sx={{ fontWeight: 900, fontSize: 22, color: VEEWASH_DASHBOARD.wfCharcoal }}>{value}</Typography>
      </Box>
    </Button>
  );
}

export default function ManagementIssuesPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const today = businessTodayYmd();
  const [dateFrom, setDateFrom] = useState(shiftDay(today, -29));
  const [dateTo, setDateTo] = useState(today);
  const [q, setQ] = useState("");
  const [source, setSource] = useState(searchParams.get("source") || "all");
  const [category, setCategory] = useState(searchParams.get("category") || "");
  const [statusGroup, setStatusGroup] = useState(searchParams.get("status_group") || "");
  const [employee, setEmployee] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [detail, setDetail] = useState(null);
  const [draft, setDraft] = useState(null);
  const [photoUrl, setPhotoUrl] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await getIssuesRegister({
        date_from: dateFrom,
        date_to: dateTo,
        q: q || undefined,
        source,
        category: category || undefined,
        status_group: statusGroup || undefined,
        employee: employee || undefined,
        page_size: 100,
      });
      if (data?.error && !data?.ok) throw new Error(data.error);
      setRows(data?.rows || []);
      setSummary(data?.summary || null);
    } catch (err) {
      setError(err?.response?.data?.error || err.message || "Could not load issues");
    } finally {
      setLoading(false);
    }
  }, [category, dateFrom, dateTo, employee, q, source, statusGroup]);

  useEffect(() => {
    const timer = setTimeout(load, 200);
    return () => clearTimeout(timer);
  }, [load]);

  const openRow = async (row) => {
    if (row.source === "rinse") {
      navigate(`/management/issues/${row.source_id}`);
      return;
    }
    setError("");
    try {
      const { data } = await getLostFoundItem(row.source_id);
      if (!data?.ok) throw new Error(data?.error || "Could not open the report");
      setDetail(data.item);
      setDraft({
        status: data.item.status,
        order_reference: data.item.order_reference || "",
        comment: "",
        reason: data.item.resolved_reason || "",
      });
      const photo = data.item.photos?.[0];
      setPhotoUrl("");
      if (photo?.id) {
        const res = await getLostFoundPhoto(photo.id);
        if (res?.data instanceof Blob && res.data.size > 8) setPhotoUrl(URL.createObjectURL(res.data));
      }
    } catch (err) {
      setError(err?.response?.data?.error || err.message || "Could not open the report");
    }
  };

  const saveEmployee = async () => {
    if (!detail || !draft) return;
    const res = await updateLostFoundStatus(detail.id, draft);
    if (!res?.data?.ok) {
      setError(res?.data?.error || "Could not update status");
      return;
    }
    setDetail(res.data.item);
    await load();
  };

  const downloadPhoto = async () => {
    const photo = detail?.photos?.[0];
    if (!photo) return;
    const res = await getLostFoundPhoto(photo.id, { download: true });
    if (!(res?.data instanceof Blob)) return;
    const url = URL.createObjectURL(res.data);
    const link = document.createElement("a");
    link.href = url;
    link.download = `issue-photo-${photo.id}.jpg`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <ManagementHubNav activeId="issues" />
      <IssuesPageShell title="Issues" maxWidth={1180}>
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 1.5 }}>
          <CountCard label="Total" value={summary?.total ?? 0} selected={!statusGroup} onClick={() => setStatusGroup("")} />
          <CountCard label="Open / new" value={summary?.open ?? 0} selected={statusGroup === "open"} onClick={() => setStatusGroup("open")} />
          <CountCard label="Under review" value={summary?.review ?? 0} selected={statusGroup === "review"} onClick={() => setStatusGroup("review")} />
          <CountCard label="Resolved / closed" value={summary?.resolved ?? 0} selected={statusGroup === "resolved"} onClick={() => setStatusGroup("resolved")} />
        </Stack>
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ mb: 1.5 }}>
          <TextField type="date" size="small" label="From" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ bgcolor: "#fff" }} />
          <TextField type="date" size="small" label="To" value={dateTo} onChange={(e) => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ bgcolor: "#fff" }} />
          <TextField size="small" label="Search" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 180, bgcolor: "#fff" }} />
          <TextField select size="small" label="Source" value={source} onChange={(e) => { setSource(e.target.value); setSearchParams(e.target.value === "all" ? {} : { source: e.target.value }); }} sx={{ minWidth: 150, bgcolor: "#fff" }}>
            <MenuItem value="all">All sources</MenuItem>
            <MenuItem value="rinse">Customer / order</MenuItem>
            <MenuItem value="employee">Employee report</MenuItem>
          </TextField>
          <TextField select size="small" label="Type" value={category} onChange={(e) => setCategory(e.target.value)} sx={{ minWidth: 180, bgcolor: "#fff" }}>
            <MenuItem value="">All types</MenuItem>
            <MenuItem value="orphan">Found Item</MenuItem>
            <MenuItem value="redry">Re-Dry Issue</MenuItem>
            <MenuItem value="equipment">Equipment Not Working</MenuItem>
            {["MISSING", "DAMAGE", "RECLEAN", "MIXED_CUSTOMER_ITEMS", "REJECTED", "FOUND", "QUALITY", "OTHER"].map((code) => (
              <MenuItem key={code} value={code}>{code}</MenuItem>
            ))}
          </TextField>
          <TextField size="small" label="Employee" value={employee} onChange={(e) => setEmployee(e.target.value)} sx={{ minWidth: 150, bgcolor: "#fff" }} />
        </Stack>
        {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
        {loading ? (
          <Box sx={{ py: 4, textAlign: "center" }}><CircularProgress size={28} /></Box>
        ) : (
          <TableContainer sx={{ bgcolor: "#fff", borderRadius: 2, overflowX: "auto" }}>
            <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>When (ET)</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Employee</TableCell>
                <TableCell>Location / order</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Photos</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7}>No issues in this range.</TableCell>
                </TableRow>
              ) : rows.map((row) => (
                <TableRow key={row.key} hover onClick={() => openRow(row)} sx={{ cursor: "pointer" }}>
                  <TableCell>{row.reported_at || row.business_date}</TableCell>
                  <TableCell>{row.source === "employee" ? "Employee" : "Customer"}</TableCell>
                  <TableCell>{row.category_label}</TableCell>
                  <TableCell>{row.employee_name || "—"}</TableCell>
                  <TableCell>{row.location || row.order_reference || row.customer_name || "—"}</TableCell>
                  <TableCell><Chip size="small" label={row.status} /></TableCell>
                  <TableCell>{row.photo_count || 0}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </TableContainer>
        )}
      </IssuesPageShell>
      <Drawer anchor="right" open={Boolean(detail)} onClose={() => setDetail(null)} PaperProps={{ sx: { width: { xs: "100%", sm: 420 }, p: 2 } }}>
        {detail ? (
          <Stack spacing={1.25}>
            <Typography sx={{ fontWeight: 900 }}>Employee report #{detail.id}</Typography>
            <Typography>{detail.location_label || detail.report_category}</Typography>
            <Typography variant="body2" color="text.secondary">{detail.reported_at_display} · {detail.employee_name}</Typography>
            {detail.notes ? <Typography>{detail.notes}</Typography> : null}
            {photoUrl ? <Box component="img" src={photoUrl} alt="" sx={{ width: "100%", borderRadius: 2, maxHeight: 240, objectFit: "cover" }} /> : <Typography variant="body2">No photo</Typography>}
            <Button onClick={downloadPhoto} disabled={!detail.photos?.length} sx={{ textTransform: "none" }}>Download photo</Button>
            <TextField select size="small" label="Status" value={draft?.status || ""} onChange={(e) => setDraft((prev) => ({ ...prev, status: e.target.value }))}>
              {statusesFor(detail).map((code) => <MenuItem key={code} value={code}>{code}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Order reference" value={draft?.order_reference || ""} onChange={(e) => setDraft((prev) => ({ ...prev, order_reference: e.target.value }))} />
            <TextField size="small" label="Comment" value={draft?.comment || ""} onChange={(e) => setDraft((prev) => ({ ...prev, comment: e.target.value }))} />
            <Button variant="contained" onClick={saveEmployee} sx={{ textTransform: "none" }}>Save status</Button>
            <Typography sx={{ fontWeight: 800, pt: 1 }}>History</Typography>
            {(detail.events || []).map((event) => (
              <Typography key={event.id} variant="body2">{event.created_at_display} · {event.event_type} · {event.actor_name || ""}</Typography>
            ))}
          </Stack>
        ) : null}
      </Drawer>
    </>
  );
}
