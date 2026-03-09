import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  InputAdornment,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { FlashOn, Search } from "@mui/icons-material";
import { getOrders } from "../api";
import { useSearchParams } from "react-router-dom";

function OrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [service, setService] = useState((searchParams.get("service") || "ALL").toUpperCase());
  const [rush, setRush] = useState((searchParams.get("rush") || "ALL").toUpperCase());
  const [status, setStatus] = useState((searchParams.get("status") || "ALL").toUpperCase());

  useEffect(() => {
    const nextService = (searchParams.get("service") || "ALL").toUpperCase();
    const nextRush = (searchParams.get("rush") || "ALL").toUpperCase();
    const nextStatus = (searchParams.get("status") || "ALL").toUpperCase();
    setService(nextService);
    setRush(nextRush);
    setStatus(nextStatus);
  }, [searchParams]);

  useEffect(() => {
    async function load() {
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
    }

    load();
  }, []);

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

      return matchSearch && matchService && matchRush && matchStatus;
    });
  }, [orders, search, service, rush, status]);

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
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}

export default OrdersPage;
