import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Divider,
  Drawer,
  Popover,
  Stack,
  Typography,
} from "@mui/material";
import {
  getManagementRinseWfReviewList,
  postManagementRinseWfSplitDecision,
} from "../../api";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";
import ManagementCopyableId from "./ManagementCopyableId";
import ManagementRinseWfReviewDrawerRow from "./ManagementRinseWfReviewDrawerRow";
import ManagementRinseWfReviewModal from "./ManagementRinseWfReviewModal";
import { fmtLbs } from "./reviewDrawerModel";
import { pickReviewSummary } from "./todayRinseModel";

function fmtTime(v) {
  if (!v) return null;
  try {
    return formatFriendlyEtWall(v) || String(v);
  } catch {
    return String(v);
  }
}

function rushLabel(flag) {
  const raw = String(flag || "").trim().toLowerCase();
  if (!raw || raw === "non-rush" || raw === "non_rush" || raw === "nonrush") {
    return "Non-Rush";
  }
  if (raw === "rush" || raw.includes("rush")) return "Rush";
  return String(flag);
}

function washerRacksText(racks) {
  if (Array.isArray(racks) && racks.length) {
    return racks.filter(Boolean).join(", ");
  }
  if (typeof racks === "string" && racks.trim()) return racks.trim();
  return null;
}

function evidenceSummaryLine(bag) {
  const marker = bag.split_marker_present ? "YES" : "NO";
  const loads =
    bag.washer_load_count != null
      ? `${bag.washer_load_count} washer load${bag.washer_load_count === 1 ? "" : "s"}`
      : null;
  const racks = washerRacksText(bag.washer_racks);
  const closeEv = bag.close_event_purpose
    ? `wash-close ${bag.close_event_purpose}`
    : null;
  const when = fmtTime(bag.relevant_time);
  return [
    `Marker ${marker}`,
    loads,
    racks ? `washers ${racks}` : null,
    closeEv,
    when,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Split Order Review row — drawer-only binary decision (no Review modal).
 */
function SplitOrderReviewRow({
  bag,
  readOnly,
  busyBagId,
  onRequestDecision,
  perfHint,
}) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const saving = busyBagId === bag.bag_id;

  return (
    <Box sx={{ py: 1.1 }} data-testid="split-order-review-row">
      <Typography sx={{ fontWeight: 800, fontSize: 14, color: "#0f172a" }}>
        {bag.customer_name || "—"}
      </Typography>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.15 }} flexWrap="wrap">
        <ManagementCopyableId value={bag.bag_id} fontSize={13} fontWeight={700} />
        <Typography sx={{ fontSize: 12, color: "#64748b" }}>
          · {rushLabel(bag.rush_flag)}
        </Typography>
      </Stack>
      <Typography sx={{ fontSize: 13, fontWeight: 700, color: "#334155", mt: 0.45 }}>
        {bag.short_reason || "Split order review"}
      </Typography>
      {(fmtLbs(bag.pre_weight_lbs) || fmtLbs(bag.post_weight_lbs)) ? (
        <Stack direction="row" spacing={1.25} sx={{ mt: 0.2 }}>
          {fmtLbs(bag.pre_weight_lbs) ? (
            <Typography data-testid="review-drawer-pre" sx={{ fontSize: 12, color: "#475569" }}>
              PRE {fmtLbs(bag.pre_weight_lbs)}
            </Typography>
          ) : null}
          {fmtLbs(bag.post_weight_lbs) ? (
            <Typography data-testid="review-drawer-post" sx={{ fontSize: 12, color: "#475569" }}>
              POST {fmtLbs(bag.post_weight_lbs)}
            </Typography>
          ) : null}
        </Stack>
      ) : null}
      <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.25 }}>
        {evidenceSummaryLine(bag)}
      </Typography>

      {!readOnly ? (
        <Stack direction="row" spacing={1} sx={{ mt: 0.9 }} flexWrap="wrap" useFlexGap>
          <Button
            size="small"
            variant="contained"
            disabled={!!busyBagId}
            onClick={(e) => onRequestDecision(e, bag, "split")}
            sx={{ textTransform: "none", fontWeight: 800, letterSpacing: 0.3 }}
          >
            {saving ? "Saving…" : "MARK SPLIT"}
          </Button>
          <Button
            size="small"
            variant="outlined"
            disabled={!!busyBagId}
            onClick={(e) => onRequestDecision(e, bag, "not_split")}
            sx={{ textTransform: "none", fontWeight: 800, letterSpacing: 0.3 }}
          >
            MARK NOT SPLIT
          </Button>
        </Stack>
      ) : (
        <Typography sx={{ mt: 0.75, fontSize: 12, color: "#94a3b8" }}>
          Day closed — read only
        </Typography>
      )}

      <Button
        size="small"
        onClick={() => setEvidenceOpen((v) => !v)}
        sx={{ mt: 0.5, px: 0, minWidth: 0, textTransform: "none", fontSize: 12, color: "#64748b" }}
      >
        {evidenceOpen ? "Hide evidence" : "VIEW EVIDENCE"}
      </Button>
      <Collapse in={evidenceOpen}>
        <Box
          sx={{
            mt: 0.5,
            mb: 0.25,
            p: 1,
            bgcolor: "#f8fafc",
            borderRadius: 1,
            border: "1px solid #e2e8f0",
          }}
        >
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            Split marker: {bag.split_marker_present ? "YES" : "NO"}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            Washer loads: {bag.washer_load_count != null ? bag.washer_load_count : "—"}
            {washerRacksText(bag.washer_racks)
              ? ` · ${washerRacksText(bag.washer_racks)}`
              : ""}
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#475569" }}>
            Wash-close: {bag.close_event_purpose || "—"}
            {fmtTime(bag.relevant_time) ? ` · ${fmtTime(bag.relevant_time)}` : ""}
          </Typography>
          {bag.split_state ? (
            <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.35 }}>
              State: {bag.split_state}
              {bag.review_reason ? ` · ${bag.review_reason}` : ""}
            </Typography>
          ) : null}
          {perfHint ? (
            <Typography sx={{ fontSize: 10, color: "#94a3b8", mt: 0.5 }}>{perfHint}</Typography>
          ) : null}
        </Box>
      </Collapse>
    </Box>
  );
}

/**
 * Dedicated REVIEW working queue — Specialty Items vs Missing From Portal vs Split Order Review.
 * Specialty / Missing: list is lightweight; Resolve in drawer; DETAILED REVIEW opens modal.
 * Split Order Review: drawer-only MARK SPLIT / MARK NOT SPLIT (no generic WF Review modal).
 */
export default function ManagementRinseWfReviewSection({
  selectedDateEt,
  rushFilter = "all",
  reviewSummary,
  snapshotUnavailable = false,
  readOnly = false,
  onRefresh,
}) {
  const scopedReview = pickReviewSummary(reviewSummary, rushFilter);
  const specialtyCount = scopedReview?.specialty_items ?? null;
  const missingCount = scopedReview?.missing_from_portal ?? null;
  const splitOrderCount = scopedReview?.split_order_review ?? null;
  const [drawer, setDrawer] = useState({ open: false, category: null });
  const [listState, setListState] = useState({
    loading: false,
    error: "",
    bags: [],
    meta: null,
  });
  const [modal, setModal] = useState({ open: false, bagId: null, seed: null });
  const [confirm, setConfirm] = useState({
    anchorEl: null,
    bag: null,
    decision: null,
  });
  const [busyBagId, setBusyBagId] = useState(null);
  const [decisionMsg, setDecisionMsg] = useState("");
  const [perf, setPerf] = useState({
    drawerOpenMs: null,
    lastDecisionSaveMs: null,
    lastDecisionRequests: null,
  });
  const drawerOpenStarted = useRef(null);

  const loadList = useCallback(
    async (category) => {
      if (!selectedDateEt || !category) return;
      const t0 = performance.now();
      setListState({ loading: true, error: "", bags: [], meta: null });
      try {
        const res = await getManagementRinseWfReviewList(selectedDateEt, {
          category,
          rush: rushFilter || "all",
          page: 1,
          page_size: 50,
        });
        const data = res?.data || {};
        const clientMs = Math.round(performance.now() - t0);
        const serverMs = data._meta?.elapsed_ms;
        if (drawerOpenStarted.current != null) {
          setPerf((p) => ({
            ...p,
            drawerOpenMs: Math.round(performance.now() - drawerOpenStarted.current),
            lastListClientMs: clientMs,
            lastListServerMs: serverMs ?? null,
            lastListQueries: data._meta?.query_count ?? null,
            scansOnList: Boolean(data._meta?.scans_loaded),
          }));
          drawerOpenStarted.current = null;
        }
        setListState({
          loading: false,
          error: data.ok === false ? data.message || data.error || "Failed to load" : "",
          bags: Array.isArray(data.bags) ? data.bags : [],
          meta: {
            ...(data._meta || {}),
            client_elapsed_ms: clientMs,
            server_elapsed_ms: serverMs,
          },
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
    drawerOpenStarted.current = performance.now();
    setDecisionMsg("");
    setDrawer({ open: true, category });
  };

  const closeDrawer = () => {
    setDrawer({ open: false, category: null });
    setListState({ loading: false, error: "", bags: [], meta: null });
    setConfirm({ anchorEl: null, bag: null, decision: null });
    setDecisionMsg("");
  };

  const title =
    drawer.category === "missing_from_portal"
      ? "Missing From Portal"
      : drawer.category === "split_order_review"
        ? "Split Order Review"
        : "Specialty Items";

  const isSplitDrawer = drawer.category === "split_order_review";

  const requestDecision = (event, bag, decision) => {
    if (readOnly || busyBagId) return;
    setConfirm({
      anchorEl: event.currentTarget,
      bag,
      decision,
    });
  };

  const closeConfirm = () => {
    if (busyBagId) return;
    setConfirm({ anchorEl: null, bag: null, decision: null });
  };

  const executeDecision = async () => {
    const bag = confirm.bag;
    const decision = confirm.decision;
    if (!bag?.bag_id || !decision || !selectedDateEt || readOnly) return;
    const t0 = performance.now();
    setBusyBagId(bag.bag_id);
    setDecisionMsg("");
    try {
      const res = await postManagementRinseWfSplitDecision(selectedDateEt, bag.bag_id, {
        decision,
      });
      if (res?.data?.ok === false) {
        setDecisionMsg(res.data.error || "Save failed");
        return;
      }
      const saveMs = Math.round(performance.now() - t0);
      // 1 POST + list reload + parent refresh (WF headline / supplies invalidate)
      setPerf((p) => ({
        ...p,
        lastDecisionSaveMs: saveMs,
        lastDecisionRequests: 3,
      }));
      setConfirm({ anchorEl: null, bag: null, decision: null });
      setDecisionMsg(
        decision === "split"
          ? `Marked ${bag.bag_id} as Split`
          : `Marked ${bag.bag_id} as Not Split`,
      );
      // Optimistic remove from queue
      setListState((prev) => ({
        ...prev,
        bags: (prev.bags || []).filter((b) => b.bag_id !== bag.bag_id),
      }));
      onRefresh?.();
      await loadList("split_order_review");
    } catch (err) {
      setDecisionMsg(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setBusyBagId(null);
    }
  };

  const confirmOpen = Boolean(confirm.anchorEl);
  const confirmIsSplit = confirm.decision === "split";

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
        PaperProps={{ sx: { width: { xs: "100%", sm: isSplitDrawer ? 440 : 460 }, p: 0 } }}
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
          {isSplitDrawer ? (
            <Alert severity="info" sx={{ mb: 1, py: 0.5 }}>
              Marker / washer-load contradiction — mark as Split or Not Split. Affects Supply.
            </Alert>
          ) : null}
          {decisionMsg ? (
            <Alert severity="success" sx={{ mb: 1, py: 0.5 }} onClose={() => setDecisionMsg("")}>
              {decisionMsg}
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
              {listState.bags.map((bag) =>
                isSplitDrawer ? (
                  <SplitOrderReviewRow
                    key={bag.bag_id}
                    bag={bag}
                    readOnly={readOnly}
                    busyBagId={busyBagId}
                    onRequestDecision={requestDecision}
                    perfHint={
                      perf.lastDecisionSaveMs != null && busyBagId == null
                        ? `Last save ${perf.lastDecisionSaveMs} ms · ${perf.lastDecisionRequests} requests`
                        : null
                    }
                  />
                ) : (
                  <ManagementRinseWfReviewDrawerRow
                    key={bag.bag_id}
                    bag={bag}
                    selectedDateEt={selectedDateEt}
                    readOnly={readOnly}
                    onDetailedReview={(seed) =>
                      setModal({ open: true, bagId: seed.bag_id, seed })
                    }
                    onSaved={() => {
                      setListState((prev) => ({
                        ...prev,
                        bags: (prev.bags || []).filter((b) => b.bag_id !== bag.bag_id),
                      }));
                      onRefresh?.();
                      if (drawer.category) loadList(drawer.category);
                    }}
                  />
                ),
              )}
            </Stack>
          )}
          {listState.meta?.elapsed_ms != null || perf.drawerOpenMs != null ? (
            <Typography sx={{ mt: 1.5, fontSize: 10, color: "#94a3b8" }} data-testid="review-drawer-perf">
              {perf.drawerOpenMs != null ? `Drawer open ${perf.drawerOpenMs} ms` : null}
              {listState.meta?.elapsed_ms != null
                ? `${perf.drawerOpenMs != null ? " · " : ""}List ${listState.meta.elapsed_ms} ms`
                : ""}
              {listState.meta?.scans_loaded ? " · scans loaded" : " · no scans"}
              {listState.meta?.query_count != null
                ? ` · ${listState.meta.query_count} queries`
                : ""}
              {perf.lastDecisionSaveMs != null
                ? ` · last decision ${perf.lastDecisionSaveMs} ms / ${perf.lastDecisionRequests} req`
                : ""}
            </Typography>
          ) : null}
        </Box>
      </Drawer>

      <Popover
        open={confirmOpen}
        anchorEl={confirm.anchorEl}
        onClose={closeConfirm}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        transformOrigin={{ vertical: "top", horizontal: "left" }}
        slotProps={{ paper: { sx: { p: 1.25, maxWidth: 280 } } }}
      >
        <Typography sx={{ fontSize: 13, fontWeight: 700, mb: 1 }}>
          {confirmIsSplit ? "Mark this order as Split?" : "Mark this order as Not Split?"}
        </Typography>
        <Typography sx={{ fontSize: 11, color: "#64748b", mb: 1.25 }}>
          Affects Supply dosing. {confirm.bag?.bag_id}
        </Typography>
        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button
            size="small"
            disabled={!!busyBagId}
            onClick={closeConfirm}
            sx={{ textTransform: "none" }}
          >
            CANCEL
          </Button>
          <Button
            size="small"
            variant="contained"
            color={confirmIsSplit ? "primary" : "inherit"}
            disabled={!!busyBagId}
            onClick={executeDecision}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            {busyBagId
              ? "Saving…"
              : confirmIsSplit
                ? "MARK SPLIT"
                : "MARK NOT SPLIT"}
          </Button>
        </Stack>
      </Popover>

      {/* Specialty / Missing only — Split Order Review never opens this modal */}
      <ManagementRinseWfReviewModal
        open={modal.open}
        bagId={modal.bagId}
        seedBag={modal.seed}
        selectedDateEt={selectedDateEt}
        readOnly={readOnly}
        onClose={() => setModal({ open: false, bagId: null, seed: null })}
        onSaved={() => {
          onRefresh?.();
          if (drawer.category && drawer.category !== "split_order_review") {
            loadList(drawer.category);
          }
        }}
      />
    </Box>
  );
}
