import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  approveFoldingException,
  bulkFoldingExceptionsAction,
  excludeFoldingException,
  getFoldingPerformanceDetail,
  listFoldingUsers,
  markFoldingExceptionReviewed,
  overrideFoldingExceptionReview,
  searchFoldingExceptions,
} from "../api";
import FoldingDateRangeFilter from "../components/folding/FoldingDateRangeFilter";
import FoldingScanEventsTable from "../components/folding/FoldingScanEventsTable";
import OrderSearchDetailDrawer from "../components/orderSearch/OrderSearchDetailDrawer";
import { getRinseOrderArchiveDetail } from "../api";
import { defaultWeekRange, foldingRangeParams } from "../utils/foldingDateRange";
import {
  formatDateTime,
  formatFoldingDuration,
  formatLbs,
} from "../utils/foldingFormat";
import { foldingExceptionLabel } from "../utils/foldingExceptionLabels";

const BULK_ACTIONS = [
  { id: "mark_reviewed", label: "Mark reviewed" },
  { id: "approve_scoring", label: "Approve for scoring" },
  { id: "exclude_scoring", label: "Exclude from scoring" },
];

export default function RinseFoldingExceptionsPage() {
  const [range, setRange] = useState(() => defaultWeekRange());
  const [filters, setFilters] = useState({
    user_name: "",
    bag_id: "",
    customer: "",
    exception_code: "",
    reviewed: "",
    approved: "",
    duration_min: "",
    duration_max: "",
  });
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [users, setUsers] = useState([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkAction, setBulkAction] = useState("mark_reviewed");
  const [bulkNote, setBulkNote] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [timelineBag, setTimelineBag] = useState("");
  const [timelineEvents, setTimelineEvents] = useState([]);
  const [orderDetailOpen, setOrderDetailOpen] = useState(false);
  const [orderDetail, setOrderDetail] = useState(null);
  const [orderDetailBag, setOrderDetailBag] = useState("");
  const [actionBag, setActionBag] = useState("");
  const [actionNote, setActionNote] = useState("");
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideUser, setOverrideUser] = useState("");
  const [overrideStart, setOverrideStart] = useState("");
  const [overrideEnd, setOverrideEnd] = useState("");

  const loadUsers = useCallback(async () => {
    try {
      const res = await listFoldingUsers();
      setUsers(res.data?.users || []);
    } catch {
      setUsers([]);
    }
  }, []);

  const search = useCallback(async () => {
    try {
      setLoading(true);
      setMessage("");
      const params = { limit: 200, ...foldingRangeParams(range) };
      if (filters.user_name) params.user_name = filters.user_name;
      if (filters.bag_id) params.bag_id = filters.bag_id;
      if (filters.customer) params.customer = filters.customer;
      if (filters.exception_code) params.exception_code = filters.exception_code;
      if (filters.duration_min) params.duration_min = Number(filters.duration_min) * 60;
      if (filters.duration_max) params.duration_max = Number(filters.duration_max) * 60;
      if (filters.reviewed === "yes") params.reviewed = "true";
      if (filters.reviewed === "no") params.reviewed = "false";
      if (filters.approved === "yes") params.approved = "true";
      if (filters.approved === "no") params.approved = "false";
      const res = await searchFoldingExceptions(params);
      setRows(res.data?.rows || []);
      setTotal(res.data?.total ?? (res.data?.rows || []).length);
      setSelected(new Set());
    } catch (e) {
      setMessage(e?.response?.data?.error || "Search failed");
    } finally {
      setLoading(false);
    }
  }, [filters, range]);

  useEffect(() => {
    loadUsers();
    search();
  }, []);

  const visibleIds = useMemo(() => rows.map((r) => r.bag_id).filter(Boolean), [rows]);
  const selectedCount = selected.size;
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  const toggleSelect = (bagId) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(bagId)) next.delete(bagId);
      else next.add(bagId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleIds));
    }
  };

  const bulkActionLabel = BULK_ACTIONS.find((a) => a.id === bulkAction)?.label || bulkAction;

  const bulkConfirmText = useMemo(() => {
    if (bulkAction === "approve_scoring") {
      return `Approve ${selectedCount} exception(s) and include them in scoring?`;
    }
    if (bulkAction === "exclude_scoring") {
      return `Exclude ${selectedCount} exception(s) from scoring?`;
    }
    return `Mark ${selectedCount} exception(s) as reviewed?`;
  }, [bulkAction, selectedCount]);

  const runBulkAction = async () => {
    const bagIds = [...selected];
    if (!bagIds.length) return;
    if (
      (bulkAction === "approve_scoring" || bulkAction === "exclude_scoring") &&
      !bulkNote.trim()
    ) {
      setMessage("Admin note is required for bulk approve and exclude.");
      return;
    }
    try {
      setBulkBusy(true);
      const res = await bulkFoldingExceptionsAction({
        bag_ids: bagIds,
        action: bulkAction,
        note: bulkNote.trim() || undefined,
      });
      const data = res.data || {};
      setBulkOpen(false);
      setBulkNote("");
      setSelected(new Set());
      setMessage(
        `Bulk ${bulkActionLabel}: updated ${data.updated ?? 0}, skipped ${data.skipped ?? 0} of ${data.requested ?? bagIds.length}.`
      );
      await search();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Bulk action failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const openTimeline = async (bagId) => {
    const bid = String(bagId || "").trim();
    if (!bid) return;
    try {
      const res = await getFoldingPerformanceDetail(bid);
      setTimelineBag(bid);
      setTimelineEvents(res.data?.scan_events || []);
      setTimelineOpen(true);
    } catch (e) {
      setMessage(e?.response?.data?.error || "Timeline failed");
    }
  };

  const openOrderDetail = async (bagId) => {
    const bid = String(bagId || "").trim();
    setOrderDetailBag(bid);
    setOrderDetailOpen(true);
    setOrderDetail(null);
    try {
      const res = await getRinseOrderArchiveDetail(bid);
      setOrderDetail(res.data);
    } catch (e) {
      setMessage(e?.response?.data?.error || "Order detail failed");
    }
  };

  const runAction = async (fn) => {
    try {
      await fn();
      setActionNote("");
      setOverrideOpen(false);
      await search();
    } catch (e) {
      setMessage(e?.response?.data?.error || "Action failed");
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1400, mx: "auto" }}>
      <Typography variant="h5" fontWeight={800} gutterBottom>
        Folding Exceptions Review
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Review data-quality exceptions, approve for gaming/scoring, or exclude. Original exception codes are kept for audit.
      </Typography>

      <FoldingDateRangeFilter value={range} onChange={setRange} sx={{ mb: 2 }} />

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1} flexWrap="wrap">
          <TextField size="small" label="Employee / user" value={filters.user_name} onChange={(e) => setFilters({ ...filters, user_name: e.target.value })} sx={{ minWidth: 140 }} />
          <TextField size="small" label="Bag ID" value={filters.bag_id} onChange={(e) => setFilters({ ...filters, bag_id: e.target.value })} />
          <TextField size="small" label="Customer" value={filters.customer} onChange={(e) => setFilters({ ...filters, customer: e.target.value })} />
          <TextField size="small" label="Exception code" value={filters.exception_code} onChange={(e) => setFilters({ ...filters, exception_code: e.target.value })} />
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Reviewed</InputLabel>
            <Select label="Reviewed" value={filters.reviewed} onChange={(e) => setFilters({ ...filters, reviewed: e.target.value })}>
              <MenuItem value="">Any</MenuItem>
              <MenuItem value="no">Unreviewed</MenuItem>
              <MenuItem value="yes">Reviewed</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel>Approved</InputLabel>
            <Select label="Approved" value={filters.approved} onChange={(e) => setFilters({ ...filters, approved: e.target.value })}>
              <MenuItem value="">Any</MenuItem>
              <MenuItem value="yes">Approved</MenuItem>
              <MenuItem value="no">Not approved</MenuItem>
            </Select>
          </FormControl>
          <TextField size="small" type="number" label="Duration min (min)" value={filters.duration_min} onChange={(e) => setFilters({ ...filters, duration_min: e.target.value })} sx={{ width: 130 }} />
          <TextField size="small" type="number" label="Duration max (min)" value={filters.duration_max} onChange={(e) => setFilters({ ...filters, duration_max: e.target.value })} sx={{ width: 130 }} />
          <Button variant="contained" onClick={search} disabled={loading}>Search</Button>
        </Stack>
      </Paper>

      {message ? (
        <Alert
          severity={message.startsWith("Bulk") ? "success" : "error"}
          sx={{ mb: 2 }}
          onClose={() => setMessage("")}
        >
          {message}
        </Alert>
      ) : null}

      {selectedCount > 0 ? (
        <Paper variant="outlined" sx={{ p: 1.5, mb: 2, bgcolor: "#f0f9ff" }}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <Typography variant="body2" fontWeight={700}>
              {selectedCount} selected
            </Typography>
            <Button size="small" onClick={() => setSelected(new Set())}>Clear selection</Button>
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel>Bulk action</InputLabel>
              <Select label="Bulk action" value={bulkAction} onChange={(e) => setBulkAction(e.target.value)}>
                {BULK_ACTIONS.map((a) => (
                  <MenuItem key={a.id} value={a.id}>{a.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              size="small"
              onClick={() => setBulkOpen(true)}
            >
              Apply to selected
            </Button>
          </Stack>
        </Paper>
      ) : null}

      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="body2" color="text.secondary">
          {total} exception row(s)
        </Typography>
        <FormControlLabel
          control={
            <Checkbox
              size="small"
              checked={allVisibleSelected}
              indeterminate={selectedCount > 0 && !allVisibleSelected}
              onChange={toggleSelectAll}
            />
          }
          label="Select all visible"
        />
      </Stack>

      <Paper variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox" />
              <TableCell>Bag</TableCell>
              <TableCell>Customer</TableCell>
              <TableCell>User</TableCell>
              <TableCell>Weight</TableCell>
              <TableCell>Start / End</TableCell>
              <TableCell>Duration</TableCell>
              <TableCell>Code</TableCell>
              <TableCell>Reason</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.bag_id} selected={selected.has(r.bag_id)}>
                <TableCell padding="checkbox">
                  <Checkbox
                    size="small"
                    checked={selected.has(r.bag_id)}
                    onChange={() => toggleSelect(r.bag_id)}
                  />
                </TableCell>
                <TableCell>{r.bag_id}</TableCell>
                <TableCell>{r.name_clean || "—"}</TableCell>
                <TableCell>{r.assigned_user_name || "—"}</TableCell>
                <TableCell>{formatLbs(r.weight_lbs ?? r.registry_weight_num)}</TableCell>
                <TableCell>
                  <Typography variant="caption" display="block">{formatDateTime(r.folding_start_at)}</Typography>
                  <Typography variant="caption" display="block">{formatDateTime(r.folding_end_at)}</Typography>
                </TableCell>
                <TableCell>{formatFoldingDuration(r.duration_seconds)}</TableCell>
                <TableCell>{r.exception_code || "—"}</TableCell>
                <TableCell sx={{ maxWidth: 200 }}>
                  {r.plain_english_reason || foldingExceptionLabel(r.exception_code)}
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5} flexWrap="wrap">
                    {r.reviewed ? <Chip size="small" label="Reviewed" /> : <Chip size="small" label="Unreviewed" variant="outlined" />}
                    {r.approved_for_scoring ? <Chip size="small" color="success" label="In scoring" /> : null}
                    {r.excluded_from_performance ? <Chip size="small" color="warning" label="Excluded" /> : null}
                  </Stack>
                </TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={0.5} justifyContent="flex-end" flexWrap="wrap">
                    <Button size="small" onClick={() => openTimeline(r.bag_id)}>Timeline</Button>
                    <Button size="small" onClick={() => openOrderDetail(r.bag_id)}>Order</Button>
                    <Button size="small" onClick={() => runAction(() => markFoldingExceptionReviewed(r.bag_id, { note: "Reviewed" }))}>Reviewed</Button>
                    <Button size="small" color="success" onClick={() => runAction(() => approveFoldingException(r.bag_id, { note: actionNote || "Approved for scoring" }))}>Approve</Button>
                    <Button size="small" color="warning" onClick={() => runAction(() => excludeFoldingException(r.bag_id, { note: "Excluded from gaming" }))}>Exclude</Button>
                    <Button
                      size="small"
                      onClick={() => {
                        setActionBag(r.bag_id);
                        setOverrideUser(r.assigned_user_name || "");
                        setOverrideStart("");
                        setOverrideEnd("");
                        setOverrideOpen(true);
                      }}
                    >
                      Override
                    </Button>
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length ? (
              <TableRow>
                <TableCell colSpan={11} align="center" sx={{ py: 3, color: "text.secondary" }}>
                  Run search to load exceptions.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Paper>

      <Dialog open={bulkOpen} onClose={() => !bulkBusy && setBulkOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Confirm bulk action</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>{bulkConfirmText}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Original exception codes will be preserved on each row.
          </Typography>
          <TextField
            label={
              bulkAction === "approve_scoring" || bulkAction === "exclude_scoring"
                ? "Admin note (required)"
                : "Admin note (optional)"
            }
            value={bulkNote}
            onChange={(e) => setBulkNote(e.target.value)}
            fullWidth
            multiline
            minRows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBulkOpen(false)} disabled={bulkBusy}>Cancel</Button>
          <Button variant="contained" onClick={runBulkAction} disabled={bulkBusy}>
            {bulkBusy ? "Applying…" : "Confirm"}
          </Button>
        </DialogActions>
      </Dialog>

      <Drawer anchor="right" open={timelineOpen} onClose={() => setTimelineOpen(false)} PaperProps={{ sx: { width: 480, p: 2 } }}>
        <Typography variant="h6" fontWeight={700} gutterBottom>Scan timeline — {timelineBag}</Typography>
        <FoldingScanEventsTable events={timelineEvents} />
      </Drawer>

      <OrderSearchDetailDrawer
        open={orderDetailOpen}
        onClose={() => { setOrderDetailOpen(false); setOrderDetail(null); }}
        detail={orderDetail}
        bagId={orderDetailBag}
        loading={!orderDetail && orderDetailOpen}
      />

      <Dialog open={overrideOpen} onClose={() => setOverrideOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Override — {actionBag}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Assign user" value={overrideUser} onChange={(e) => setOverrideUser(e.target.value)} fullWidth />
            <TextField label="Folding start (ISO)" value={overrideStart} onChange={(e) => setOverrideStart(e.target.value)} fullWidth />
            <TextField label="Folding end (ISO)" value={overrideEnd} onChange={(e) => setOverrideEnd(e.target.value)} fullWidth />
            <TextField label="Admin note" value={actionNote} onChange={(e) => setActionNote(e.target.value)} fullWidth multiline rows={2} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOverrideOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => runAction(() => overrideFoldingExceptionReview(actionBag, {
              assigned_user_name: overrideUser || undefined,
              folding_start_at: overrideStart || undefined,
              folding_end_at: overrideEnd || undefined,
              admin_notes: actionNote || undefined,
              notes: actionNote || undefined,
            }))}
          >
            Save override
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
