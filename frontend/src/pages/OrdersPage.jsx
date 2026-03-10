import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Chip,
  CircularProgress,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { FlashOn, Search } from "@mui/icons-material";
import { deleteOrder, getOrders, updateOrder } from "../api";
import { useSearchParams } from "react-router-dom";

function OrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [service, setService] = useState((searchParams.get("service") || "ALL").toUpperCase());
  const [rush, setRush] = useState((searchParams.get("rush") || "ALL").toUpperCase());
  const [status, setStatus] = useState((searchParams.get("status") || "ALL").toUpperCase());
  const [alpha, setAlpha] = useState("ALL");
  const [editRow, setEditRow] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const nextService = (searchParams.get("service") || "ALL").toUpperCase();
    const nextRush = (searchParams.get("rush") || "ALL").toUpperCase();
    const nextStatus = (searchParams.get("status") || "ALL").toUpperCase();
    setService(nextService);
    setRush(nextRush);
    setStatus(nextStatus);
  }, [searchParams]);

  const loadOrders = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getOrders();
      const rows = Array.isArray(res.data) ? res.data : [];
      setOrders(rows);
    } catch (error) {
      console.error(error);
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  const handleFullRefresh = async () => {
    setSearch("");
    setService("ALL");
    setRush("ALL");
    setStatus("ALL");
    setAlpha("ALL");
    setSearchParams({});
    await loadOrders();
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();

    return orders.filter((row) => {
      const rowService = String(row?.service_type || "").toUpperCase();
      const rowRush = String(row?.rush_type || "").toUpperCase();
      const rowStatus = String(row?.status || "").toUpperCase();

      const matchSearch =
        !q ||
        String(row?.name_clean || "").toLowerCase().includes(q) ||
        String(row?.id || "").includes(q);

      const matchService = service === "ALL" || rowService === service;
      const matchRush = rush === "ALL" || rowRush === rush;
      const matchStatus = status === "ALL" || rowStatus === status;
      const name = String(row?.name_clean || "").trim().toUpperCase();
      const first = name.charAt(0);
      const matchAlpha = alpha === "ALL" || first === alpha;

      return matchSearch && matchService && matchRush && matchStatus && matchAlpha;
    });
  }, [orders, search, service, rush, status, alpha]);

  const stats = useMemo(() => {
    const total = filtered.length;
    const wf = filtered.filter((row) => String(row?.service_type || "").toUpperCase() === "WF").length;
    const hd = filtered.filter((row) => String(row?.service_type || "").toUpperCase() === "HD").length;
    const rushCount = filtered.filter((row) => String(row?.rush_type || "").toUpperCase() === "RUSH").length;

    return { total, wf, hd, rushCount };
  }, [filtered]);

  const formatMeasure = (row) => {
    const serviceType = String(row?.service_type || "").toUpperCase();
    const raw = Number(row?.weight_num ?? 0);

    if (serviceType === "WF") return `${raw.toFixed(2)} lb`;
    if (serviceType === "HD") return `${Math.round(raw)} pcs`;
    return "-";
  };

  const formatDateOnly = (value) => {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value).split(" ")[0];
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  };

  const applyParamFilters = (nextService, nextRush, nextStatus) => {
    const next = {};
    if (nextService !== "ALL") next.service = nextService;
    if (nextRush !== "ALL") next.rush = nextRush;
    if (nextStatus !== "ALL") next.status = nextStatus;
    setSearchParams(next);
  };

  return (
    <Box sx={{ minHeight: "100vh", background: "#f3f4f6", px: { xs: 1.2, md: 2.4 }, py: 1.5 }}>
      <Typography sx={{ fontSize: 30, fontWeight: 900, lineHeight: 1 }}>Orders</Typography>
      <Typography sx={{ color: "#6b7280", mt: 0.4 }}>Live staging queue</Typography>

      <Stack direction="row" spacing={1} sx={{ mt: 1.2, overflowX: "auto", pb: 0.4 }}>
        <Chip label={`${stats.total} visible`} color="primary" />
        <Chip label={`WF ${stats.wf}`} />
        <Chip label={`HD ${stats.hd}`} />
        <Chip icon={<FlashOn />} label={`RUSH ${stats.rushCount}`} color="error" variant="outlined" />
        <Button size="small" variant="outlined" onClick={() => window.print()}>
          Print
        </Button>
        <Button size="small" variant="outlined" onClick={handleFullRefresh} disabled={loading}>
          Full Refresh
        </Button>
      </Stack>

      <Paper sx={{ p: 1.2, borderRadius: 2, mt: 1.2 }}>
        <TextField
          fullWidth
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or id"
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search fontSize="small" />
              </InputAdornment>
            ),
          }}
        />

        <Stack direction="row" spacing={1} sx={{ mt: 1, overflowX: "auto", pb: 0.5 }}>
          {["ALL", "WF", "HD"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={service === item ? "warning" : "default"}
              onClick={() => {
                setService(item);
                applyParamFilters(item, rush, status);
              }}
            />
          ))}
          {["ALL", "RUSH", "NON-RUSH"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={rush === item ? "error" : "default"}
              onClick={() => {
                setRush(item);
                applyParamFilters(service, item, status);
              }}
            />
          ))}
          {["ALL", "PENDING", "PROCESSED", "CHECKED_OUT"].map((item) => (
            <Chip
              key={item}
              label={item}
              clickable
              color={status === item ? "success" : "default"}
              onClick={() => {
                setStatus(item);
                applyParamFilters(service, rush, item);
              }}
            />
          ))}
        </Stack>

        <Stack direction="row" spacing={0.7} sx={{ mt: 0.5, overflowX: "auto", pb: 0.3 }}>
          {["ALL", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"].map((letter) => (
            <Chip
              key={letter}
              label={letter}
              clickable
              color={alpha === letter ? "primary" : "default"}
              onClick={() => setAlpha(letter)}
            />
          ))}
        </Stack>
      </Paper>

      {loading ? (
        <Stack alignItems="center" justifyContent="center" sx={{ py: 8 }} spacing={1.2}>
          <CircularProgress />
          <Typography color="text.secondary">Loading orders...</Typography>
        </Stack>
      ) : filtered.length === 0 ? (
        <Alert severity="info" sx={{ mt: 1.5 }}>
          No orders found for this filter.
        </Alert>
      ) : (
        <Stack spacing={1} sx={{ mt: 1.2 }}>
          {filtered.map((row) => {
            const isRush = String(row?.rush_type || "").toUpperCase() === "RUSH";
            const rowStatus = String(row?.status || "PENDING").toUpperCase();

            return (
              <Paper
                key={row.id}
                sx={{
                  p: 1.2,
                  borderRadius: 2,
                  border: `1px solid ${isRush ? "#fca5a5" : "#d1d5db"}`,
                }}
              >
                <Stack spacing={0.7}>
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Typography sx={{ fontSize: 20, fontWeight: 800 }}>{row.name_clean || "-"}</Typography>
                    <Chip size="small" label={`#${row.id}`} />
                  </Stack>

                  <Typography sx={{ color: "#4b5563", fontWeight: 600 }}>
                    {formatMeasure(row)} • {formatDateOnly(row.date_clean)}
                  </Typography>

                  <Stack direction="row" spacing={1}>
                    <Chip size="small" label={row.service_type || "-"} color="warning" />
                    <Chip size="small" label={isRush ? "RUSH" : "NON-RUSH"} color={isRush ? "error" : "success"} />
                    <Chip size="small" label={rowStatus} variant="outlined" />
                  </Stack>

                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="outlined" onClick={() => setEditRow({
                      id: row.id,
                      date_clean: String(row.date_clean || "").slice(0, 10),
                      name_clean: row.name_clean || "",
                      weight_num: row.weight_num ?? "",
                      service_type: row.service_type || "WF",
                    })}>
                      Edit
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      onClick={async () => {
                        if (!window.confirm(`Delete order #${row.id}?`)) return;
                        try {
                          await deleteOrder(row.id);
                          setOrders((prev) => prev.filter((r) => r.id !== row.id));
                        } catch (error) {
                          console.error(error);
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </Stack>
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      )}

      <Dialog open={!!editRow} onClose={() => setEditRow(null)} fullWidth maxWidth="sm">
        <DialogTitle>Edit Order</DialogTitle>
        <DialogContent>
          {editRow && (
            <Stack spacing={1.2} sx={{ mt: 0.6 }}>
              <TextField
                label="Date"
                type="date"
                value={editRow.date_clean}
                InputLabelProps={{ shrink: true }}
                onChange={(e) => setEditRow((p) => ({ ...p, date_clean: e.target.value }))}
              />
              <TextField
                label="Name"
                value={editRow.name_clean}
                onChange={(e) => setEditRow((p) => ({ ...p, name_clean: e.target.value }))}
              />
              <TextField
                label="Weight / Count"
                type="number"
                value={editRow.weight_num}
                onChange={(e) => setEditRow((p) => ({ ...p, weight_num: e.target.value }))}
              />
              <TextField
                label="Service"
                select
                value={editRow.service_type}
                onChange={(e) => setEditRow((p) => ({ ...p, service_type: e.target.value }))}
              >
                <MenuItem value="WF">WF</MenuItem>
                <MenuItem value="HD">HD</MenuItem>
              </TextField>
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditRow(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!editRow || saving}
            onClick={async () => {
              if (!editRow) return;
              try {
                setSaving(true);
                await updateOrder(editRow.id, {
                  date_clean: editRow.date_clean,
                  name_clean: editRow.name_clean,
                  weight_num: Number(editRow.weight_num),
                  service_type: editRow.service_type,
                });
                setOrders((prev) =>
                  prev.map((r) =>
                    r.id === editRow.id
                      ? {
                          ...r,
                          date_clean: editRow.date_clean,
                          name_clean: editRow.name_clean,
                          weight_num: Number(editRow.weight_num),
                          service_type: editRow.service_type,
                        }
                      : r
                  )
                );
                setEditRow(null);
              } catch (error) {
                console.error(error);
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

export default OrdersPage;
