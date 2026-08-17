import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Drawer,
  Stack,
  Typography,
} from "@mui/material";
import { getManagementRinseWfReviewList } from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import ManagementCopyableId from "./ManagementCopyableId";
import ManagementRinseWfReviewModal from "./ManagementRinseWfReviewModal";

function fmtTime(v) {
  if (!v) return null;
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

/**
 * Dedicated REVIEW working queue — Specialty Items vs Missing From Portal.
 * List is lightweight; REVIEW opens one-bag modal (detail on demand).
 */
export default function ManagementRinseWfReviewSection({
  selectedDateEt,
  rushFilter = "all",
  reviewSummary,
  snapshotUnavailable = false,
  readOnly = false,
  onRefresh,
}) {
  const specialtyCount = reviewSummary?.specialty_items ?? null;
  const missingCount = reviewSummary?.missing_from_portal ?? null;
  const splitOrderCount = reviewSummary?.split_order_review ?? null;
  const [drawer, setDrawer] = useState({ open: false, category: null });
  const [listState, setListState] = useState({
    loading: false,
    error: "",
    bags: [],
    meta: null,
  });
  const [modal, setModal] = useState({ open: false, bagId: null, seed: null });

  const loadList = useCallback(
    async (category) => {
      if (!selectedDateEt || !category) return;
      setListState({ loading: true, error: "", bags: [], meta: null });
      try {
        const res = await getManagementRinseWfReviewList(selectedDateEt, {
          category,
          rush: rushFilter || "all",
          page: 1,
          page_size: 50,
        });
        const data = res?.data || {};
        setListState({
          loading: false,
          error: data.ok === false ? data.message || data.error || "Failed to load" : "",
          bags: Array.isArray(data.bags) ? data.bags : [],
          meta: data._meta || null,
        });
      } catch (err) {
        setListState({
          loading: false,
          error: err?.response?.data?.error || err?.message || "Failed to load review list",
          bags: [],
          meta: null,
        });
      }
    },
    [selectedDateEt, rushFilter],
  );

  useEffect(() => {
    if (drawer.open && drawer.category) {
      loadList(drawer.category);
    }
  }, [drawer.open, drawer.category, loadList]);

  const openCategory = (category) => {
    if (snapshotUnavailable) return;
    setDrawer({ open: true, category });
  };

  const closeDrawer = () => {
    setDrawer({ open: false, category: null });
    setListState({ loading: false, error: "", bags: [], meta: null });
  };

  const title =
    drawer.category === "missing_from_portal"
      ? "Missing From Portal"
      : drawer.category === "split_order_review"
        ? "Split Order Review"
        : "Specialty Items";

  return (
    <Box sx={{ mt: 0.5, mb: 1.5 }}>
      <Stack direction="row" alignItems="baseline" spacing={0.75} sx={{ mb: 0.75 }}>
        <Typography
          sx={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: 0.8,
            textTransform: "uppercase",
            color: "#64748b",
          }}
        >
          Review
        </Typography>
        <Typography sx={{ fontSize: 10, fontWeight: 700, color: "#94a3b8" }}>
          Working queue
        </Typography>
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr 1fr" },
          gap: 0.75,
        }}
      >
        <Button
          variant="outlined"
          disabled={snapshotUnavailable}
          onClick={() => openCategory("specialty_items")}
          sx={{
            justifyContent: "space-between",
            textTransform: "none",
            px: 1.25,
            py: 1.1,
            borderColor: "#cbd5e1",
            bgcolor: "#fff",
          }}
        >
          <Typography sx={{ fontWeight: 700, fontSize: 14, color: "#0f172a" }}>
            Specialty Items
          </Typography>
          <Typography sx={{ fontWeight: 800, fontSize: 18, color: "#0f172a" }}>
            {snapshotUnavailable || specialtyCount == null ? "—" : specialtyCount}
          </Typography>
        </Button>
        <Button
          variant="outlined"
          disabled={snapshotUnavailable}
          onClick={() => openCategory("missing_from_portal")}
          sx={{
            justifyContent: "space-between",
            textTransform: "none",
            px: 1.25,
            py: 1.1,
            borderColor: "#cbd5e1",
            bgcolor: "#fff",
          }}
        >
          <Typography sx={{ fontWeight: 700, fontSize: 14, color: "#0f172a" }}>
            Missing From Portal
          </Typography>
          <Typography sx={{ fontWeight: 800, fontSize: 18, color: "#0f172a" }}>
            {snapshotUnavailable || missingCount == null ? "—" : missingCount}
          </Typography>
        </Button>
        <Button
          variant="outlined"
          disabled={snapshotUnavailable}
          onClick={() => openCategory("split_order_review")}
          sx={{
            justifyContent: "space-between",
            textTransform: "none",
            px: 1.25,
            py: 1.1,
            borderColor: "#cbd5e1",
            bgcolor: "#fff",
          }}
        >
          <Typography sx={{ fontWeight: 700, fontSize: 14, color: "#0f172a" }}>
            Split Order Review
          </Typography>
          <Typography sx={{ fontWeight: 800, fontSize: 18, color: "#0f172a" }}>
            {snapshotUnavailable || splitOrderCount == null ? "—" : splitOrderCount}
          </Typography>
        </Button>
      </Box>

      <Drawer
        anchor="right"
        open={drawer.open}
        onClose={closeDrawer}
        PaperProps={{ sx: { width: { xs: "100%", sm: 420 }, p: 0 } }}
      >
        <Box sx={{ p: 1.5 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{title}</Typography>
            <Button size="small" onClick={closeDrawer} sx={{ textTransform: "none" }}>
              Close
            </Button>
          </Stack>
          {drawer.category === "missing_from_portal" ? (
            <Alert severity="info" sx={{ mb: 1, py: 0.5 }}>
              Data / evidence exception — not an automatic employee quality issue.
            </Alert>
          ) : null}
          {drawer.category === "split_order_review" ? (
            <Alert severity="info" sx={{ mb: 1, py: 0.5 }}>
              Marker / washer-load contradiction — mark as Split or Not Split.
            </Alert>
          ) : null}
          {listState.loading ? (
            <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
              <CircularProgress size={28} />
            </Box>
          ) : listState.error ? (
            <Alert severity="error">{listState.error}</Alert>
          ) : listState.bags.length === 0 ? (
            <Typography sx={{ color: "#64748b", fontSize: 13, py: 2 }}>
              No bags in this queue.
            </Typography>
          ) : (
            <Stack spacing={0} divider={<Divider />}>
              {listState.bags.map((bag) => (
                <Box key={bag.bag_id} sx={{ py: 1.1 }}>
                  <Typography sx={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
                    {bag.customer_name || "—"}
                  </Typography>
                  <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.15 }}>
                    <ManagementCopyableId value={bag.bag_id} fontSize={13} fontWeight={700} />
                    {bag.rush_flag ? (
                      <Typography sx={{ fontSize: 12, color: "#64748b" }}>
                        · {bag.rush_flag}
                      </Typography>
                    ) : null}
                  </Stack>
                  <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.25 }}>
                    {bag.short_reason || title}
                    {bag.specialty_summary ? ` · ${bag.specialty_summary}` : ""}
                    {bag.washer_load_count != null
                      ? ` · ${bag.washer_load_count} washer load${bag.washer_load_count === 1 ? "" : "s"}`
                      : ""}
                    {bag.split_marker_present ? " · marker" : ""}
                  </Typography>
                  <Typography sx={{ fontSize: 12, color: "#94a3b8" }}>
                    {[bag.employee, fmtTime(bag.relevant_time)].filter(Boolean).join(" · ") || "—"}
                  </Typography>
                  <Button
                    size="small"
                    variant="contained"
                    onClick={() =>
                      setModal({ open: true, bagId: bag.bag_id, seed: bag })
                    }
                    sx={{ mt: 0.75, textTransform: "none", fontWeight: 700 }}
                  >
                    Review
                  </Button>
                </Box>
              ))}
            </Stack>
          )}
          {listState.meta?.elapsed_ms != null ? (
            <Typography sx={{ mt: 1.5, fontSize: 10, color: "#94a3b8" }}>
              List {listState.meta.elapsed_ms} ms
              {listState.meta.scans_loaded ? " · scans loaded" : " · no scans"}
              {listState.meta.query_count != null
                ? ` · ${listState.meta.query_count} queries`
                : ""}
            </Typography>
          ) : null}
        </Box>
      </Drawer>

      <ManagementRinseWfReviewModal
        open={modal.open}
        bagId={modal.bagId}
        seedBag={modal.seed}
        selectedDateEt={selectedDateEt}
        readOnly={readOnly}
        onClose={() => setModal({ open: false, bagId: null, seed: null })}
        onSaved={() => {
          onRefresh?.();
          if (drawer.category) loadList(drawer.category);
        }}
      />
    </Box>
  );
}
