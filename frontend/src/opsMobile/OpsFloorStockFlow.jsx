import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  InputAdornment,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import CloseIcon from "@mui/icons-material/Close";
import SearchIcon from "@mui/icons-material/Search";
import {
  getInventoryStockCheckDraft,
  saveInventoryStockCheckDraft,
  submitInventoryStockCheck,
} from "../api";
import OpsMobileShell from "./OpsMobileShell";
import OpsStickyActionBar from "./OpsStickyActionBar";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import OpsFloorStockCard from "./OpsFloorStockCard";
import {
  createStockDraftAutosave,
  createStockSubmitController,
} from "./createStockDraftAutosave";
import {
  emptyFloorFilterMessage,
  filterFloorStockItems,
  stockCheckDueItems,
  stockCheckProgress,
} from "../utils/inventoryFloorHelpers";
import { groupItemsByCategory } from "../utils/inventoryHelpers";

const MODES = [
  { key: "count", label: "Count" },
  { key: "low", label: "Low" },
  { key: "out", label: "Out" },
  { key: "recount", label: "Recount" },
];

/**
 * PIN / shared-device floor stock-count flow.
 */
export default function OpsFloorStockFlow({
  user,
  items,
  categories,
  varianceThreshold,
  onRefresh,
  onBack,
  onLock,
  onDone,
}) {
  const displayName = user?.display_name || user?.username || "Unknown";
  const [phase, setPhase] = useState("counting"); // counting | completed
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [mode, setMode] = useState("count");
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [counts, setCounts] = useState({});
  const [notes, setNotes] = useState({});
  const [varianceReasons, setVarianceReasons] = useState({});
  const [statuses, setStatuses] = useState({});
  const [recounts, setRecounts] = useState({});
  const [threshold, setThreshold] = useState(varianceThreshold ?? 5);
  const [saveState, setSaveState] = useState(""); // '' | saving | saved | error
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitSummary, setSubmitSummary] = useState(null);
  const [pendingTick, setPendingTick] = useState(0);

  const stateRef = useRef({});
  const autosaveRef = useRef(null);
  const submitRef = useRef(null);
  const searchInputRef = useRef(null);

  stateRef.current = { counts, notes, varianceReasons, statuses, recounts, items };

  const buildLines = useCallback(() => {
    const { counts: c, notes: n, varianceReasons: vr, statuses: st, recounts: rc, items: all } =
      stateRef.current;
    const weekly = stockCheckDueItems(all);
    return weekly
      .map((i) => {
        const isStatus = String(i.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
        const needsRecount = Boolean(rc[i.id]);
        if (isStatus) {
          const status = st[i.id];
          if (!status && !needsRecount) return null;
          return {
            item_id: i.id,
            status_level: status || i.status_level || "OK",
            counted_qty: null,
            note: n[i.id] || null,
            variance_reason: null,
            needs_recount: needsRecount,
          };
        }
        if (needsRecount) {
          return {
            item_id: i.id,
            counted_qty: c[i.id] === "" || c[i.id] == null ? null : parseFloat(c[i.id]),
            note: n[i.id] || "Marked for recount",
            variance_reason: vr[i.id] || null,
            needs_recount: true,
          };
        }
        if (c[i.id] === "" || c[i.id] == null) return null;
        return {
          item_id: i.id,
          counted_qty: parseFloat(c[i.id]),
          note: n[i.id] || null,
          variance_reason: vr[i.id] || null,
          needs_recount: false,
        };
      })
      .filter(Boolean);
  }, []);

  useEffect(() => {
    autosaveRef.current = createStockDraftAutosave({
      debounceMs: 450,
      buildLines,
      getNotesMeta: () => `Draft by ${displayName}`,
      isBlocked: () => phase !== "counting" || submitting,
      saveDraft: async ({ lines, notes: meta }) => {
        setSaveState("saving");
        await saveInventoryStockCheckDraft({ lines, notes: meta });
      },
      onSaved: () => {
        setSaveState("saved");
        setError("");
        setPendingTick((x) => x + 1);
      },
      onError: (msg) => {
        setSaveState("error");
        setError(msg || "Couldn’t save. Try again.");
      },
    });
    submitRef.current = createStockSubmitController({
      buildLines,
      isBlocked: () => phase !== "counting",
      submitCheck: async ({ lines }) => {
        const res = await submitInventoryStockCheck({
          lines,
          oneshot: true,
          notes: `Weekly check ${new Date().toISOString().slice(0, 10)}`,
        });
        return res;
      },
      onSuccess: (res) => {
        const submitted = res?.data?.lines_submitted;
        setSubmitSummary({
          lines: submitted ?? buildLines().length,
        });
        setCounts({});
        setNotes({});
        setVarianceReasons({});
        setStatuses({});
        setRecounts({});
        setPhase("completed");
        setError("");
        onRefresh?.();
      },
      onError: (msg) => setError(msg || "Couldn’t submit. Try again."),
    });
    return () => autosaveRef.current?.dispose();
  }, [buildLines, displayName, phase, submitting, onRefresh]);

  const loadDraft = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError("");
      const res = await getInventoryStockCheckDraft();
      setThreshold(res?.data?.variance_threshold ?? varianceThreshold ?? 5);
      const draft = res?.data?.draft;
      if (draft?.lines) {
        const nextCounts = {};
        const nextNotes = {};
        const nextReasons = {};
        const nextStatuses = {};
        const nextRecounts = {};
        Object.values(draft.lines).forEach((ln) => {
          nextCounts[ln.item_id] = ln.counted_qty ?? "";
          nextNotes[ln.item_id] = ln.note ?? "";
          nextReasons[ln.item_id] = ln.variance_reason ?? "";
          if (ln.status_level) nextStatuses[ln.item_id] = ln.status_level;
          if (ln.needs_recount) nextRecounts[ln.item_id] = true;
        });
        setCounts(nextCounts);
        setNotes(nextNotes);
        setVarianceReasons(nextReasons);
        setStatuses(nextStatuses);
        setRecounts(nextRecounts);
      }
      // Auto-seed status items (existing start semantics) without Start gate.
      // Surface unresolved item.needs_recount flags in draft recount map.
      setStatuses((prev) => {
        const next = { ...prev };
        stockCheckDueItems(items).forEach((i) => {
          if (String(i.tracking_mode || "QUANTITY").toUpperCase() !== "STATUS") return;
          if (next[i.id]) return;
          next[i.id] = i.status_level || "OK";
        });
        return next;
      });
      setRecounts((prev) => {
        const next = { ...prev };
        (items || []).forEach((i) => {
          if (i.needs_recount && next[i.id] == null) next[i.id] = true;
        });
        return next;
      });
      setPhase("counting");
    } catch {
      setLoadError("Couldn’t load. Try again.");
    } finally {
      setLoading(false);
    }
  }, [varianceThreshold, items]);

  useEffect(() => {
    loadDraft();
  }, [loadDraft]);

  useEffect(() => {
    if (searchOpen) {
      const t = setTimeout(() => searchInputRef.current?.focus?.(), 50);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [searchOpen]);

  const scheduleSave = () => {
    setSaveState("saving");
    autosaveRef.current?.schedule();
    setPendingTick((x) => x + 1);
  };

  const visibleItems = useMemo(
    () => filterFloorStockItems(items, mode, { search, draftRecounts: recounts }),
    [items, mode, search, recounts],
  );

  const grouped = useMemo(
    () => groupItemsByCategory(visibleItems, categories),
    [visibleItems, categories],
  );

  const progress = stockCheckProgress(items, counts, statuses, recounts);
  void pendingTick;

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await submitRef.current?.submit();
    } finally {
      setSubmitting(false);
    }
  };

  if (phase === "completed") {
    return (
      <OpsMobileShell contentSx={{ gap: 1.5, pb: 10 }}>
        <Box
          sx={{
            width: "100%",
            borderRadius: `${OPS_MOBILE.radius.card}px`,
            bgcolor: alpha("#fff", 0.96),
            p: 2,
            boxShadow: `0 8px 28px -16px ${alpha(OPS_MOBILE.navy, 0.35)}`,
          }}
        >
          <OpsTopBar title="Stock" onBack={onBack} backLabel="PIN" onLock={onLock} sticky />
          <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 2 }}>
            <CheckCircleOutlineIcon sx={{ color: OPS_MOBILE.success, fontSize: 28 }} />
            <Box>
              <Typography sx={{ fontWeight: 900, color: OPS_MOBILE.navy }}>Stock check submitted</Typography>
              {submitSummary?.lines != null ? (
                <Typography sx={{ fontWeight: 700, color: OPS_MOBILE.muted, fontSize: "0.9rem" }}>
                  {submitSummary.lines} item{submitSummary.lines === 1 ? "" : "s"}
                </Typography>
              ) : null}
            </Box>
          </Stack>
        </Box>
        <OpsStickyActionBar
          sx={{
            position: "fixed",
            left: 0,
            right: 0,
            bottom: 0,
            px: 2,
            maxWidth: 420,
            mx: "auto",
          }}
        >
          <Button
            fullWidth
            variant="contained"
            onClick={onDone}
            sx={{
              minHeight: 56,
              textTransform: "none",
              fontWeight: 900,
              fontSize: "1.05rem",
              borderRadius: `${OPS_MOBILE.radius.button}px`,
              bgcolor: OPS_MOBILE.navy,
            }}
          >
            Done
          </Button>
        </OpsStickyActionBar>
      </OpsMobileShell>
    );
  }

  return (
    <OpsMobileShell contentSx={{ gap: 1.25, pb: 10 }}>
      <Box
        sx={{
          width: "100%",
          borderRadius: `${OPS_MOBILE.radius.card}px`,
          bgcolor: alpha("#fff", 0.96),
          p: { xs: 1.5, sm: 2 },
          boxShadow: `0 8px 28px -16px ${alpha(OPS_MOBILE.navy, 0.35)}`,
          display: "flex",
          flexDirection: "column",
          gap: 1.25,
        }}
      >
        <OpsTopBar title="Stock" onBack={onBack} backLabel="PIN" onLock={onLock} sticky />

        <Stack direction="row" alignItems="center" spacing={1}>
          {mode === "count" ? (
            <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy, flexShrink: 0 }}>
              {progress.done} of {progress.total}
            </Typography>
          ) : (
            <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.muted, flexShrink: 0 }}>
              {visibleItems.length}
            </Typography>
          )}
          <Box sx={{ flex: 1 }} />
          {saveState === "saving" ? (
            <Typography sx={{ fontWeight: 700, fontSize: "0.8rem", color: OPS_MOBILE.muted }}>Saving…</Typography>
          ) : null}
          {saveState === "saved" ? (
            <Typography sx={{ fontWeight: 700, fontSize: "0.8rem", color: OPS_MOBILE.success }}>Saved</Typography>
          ) : null}
          <IconButton
            aria-label="Search"
            onClick={() => {
              setSearchOpen((v) => {
                if (v) setSearch("");
                return !v;
              });
            }}
            sx={{ width: 48, height: 48 }}
          >
            {searchOpen ? <CloseIcon /> : <SearchIcon />}
          </IconButton>
        </Stack>

        {mode === "count" && progress.total > 0 ? (
          <LinearProgress
            variant="determinate"
            value={progress.total ? (100 * progress.done) / progress.total : 0}
            sx={{
              height: 5,
              borderRadius: 99,
              bgcolor: alpha(OPS_MOBILE.navy, 0.08),
              "& .MuiLinearProgress-bar": { bgcolor: OPS_MOBILE.cobalt, borderRadius: 99 },
            }}
          />
        ) : null}

        <Box
          sx={{
            display: "flex",
            gap: 0.75,
            overflowX: "auto",
            WebkitOverflowScrolling: "touch",
            pb: 0.25,
          }}
        >
          {MODES.map((m) => {
            const active = mode === m.key;
            return (
              <Button
                key={m.key}
                onClick={() => setMode(m.key)}
                sx={{
                  flexShrink: 0,
                  minHeight: 40,
                  px: 1.5,
                  borderRadius: 999,
                  textTransform: "none",
                  fontWeight: active ? 900 : 700,
                  fontSize: m.key === "count" ? "0.95rem" : "0.85rem",
                  bgcolor: active ? alpha(OPS_MOBILE.cobalt, 0.18) : alpha(OPS_MOBILE.navy, 0.04),
                  color: OPS_MOBILE.navy,
                }}
              >
                {m.label}
              </Button>
            );
          })}
        </Box>

        {searchOpen ? (
          <TextField
            inputRef={searchInputRef}
            fullWidth
            size="small"
            placeholder="Name, SKU, barcode…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: search ? (
                <InputAdornment position="end">
                  <IconButton size="small" aria-label="Clear search" onClick={() => setSearch("")}>
                    <CloseIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : null,
            }}
          />
        ) : null}

        {error ? (
          <Alert
            severity="error"
            action={
              saveState === "error" ? (
                <Button color="inherit" size="small" onClick={() => autosaveRef.current?.flushNow()}>
                  Retry
                </Button>
              ) : null
            }
            onClose={() => setError("")}
            sx={{ borderRadius: 2 }}
          >
            {error}
          </Alert>
        ) : null}

        {loadError ? (
          <Stack spacing={1.5} sx={{ py: 3, alignItems: "center" }}>
            <Typography sx={{ fontWeight: 800 }}>{loadError}</Typography>
            <Button onClick={loadDraft} sx={{ fontWeight: 800, textTransform: "none", minHeight: 48 }}>
              Retry
            </Button>
          </Stack>
        ) : null}

        {loading && !loadError ? (
          <Stack spacing={1.25}>
            {[0, 1, 2].map((i) => (
              <Box
                key={i}
                sx={{
                  height: 96,
                  borderRadius: `${OPS_MOBILE.radius.card}px`,
                  bgcolor: alpha(OPS_MOBILE.navy, 0.06),
                }}
              />
            ))}
          </Stack>
        ) : null}

        {!loading && !loadError && visibleItems.length === 0 ? (
          <Typography sx={{ fontWeight: 800, textAlign: "center", py: 4, color: OPS_MOBILE.navy }}>
            {emptyFloorFilterMessage(mode)}
          </Typography>
        ) : null}

        {!loading && !loadError
          ? grouped.map((cat) => (
              <Box key={cat.id} sx={{ display: "flex", flexDirection: "column", gap: 1.25 }}>
                <Typography
                  sx={{
                    fontWeight: 800,
                    fontSize: "0.75rem",
                    letterSpacing: 0.4,
                    textTransform: "uppercase",
                    color: OPS_MOBILE.muted,
                    px: 0.25,
                  }}
                >
                  {cat.name}
                </Typography>
                {cat.items.map((item) => (
                  <OpsFloorStockCard
                    key={item.id}
                    item={item}
                    countValue={counts[item.id] ?? ""}
                    noteValue={notes[item.id] ?? ""}
                    varianceReason={varianceReasons[item.id] ?? ""}
                    varianceThreshold={threshold}
                    statusValue={statuses[item.id] ?? item.status_level ?? "OK"}
                    needsRecount={Boolean(recounts[item.id])}
                    onCountChange={(v) => {
                      setCounts((p) => ({ ...p, [item.id]: v }));
                      scheduleSave();
                    }}
                    onNoteChange={(v) => {
                      setNotes((p) => ({ ...p, [item.id]: v }));
                      scheduleSave();
                    }}
                    onVarianceReasonChange={(v) => {
                      setVarianceReasons((p) => ({ ...p, [item.id]: v }));
                      scheduleSave();
                    }}
                    onStatusChange={(v) => {
                      setStatuses((p) => ({ ...p, [item.id]: v }));
                      scheduleSave();
                    }}
                    onRecountChange={(v) => {
                      setRecounts((p) => ({ ...p, [item.id]: Boolean(v) }));
                      scheduleSave();
                    }}
                  />
                ))}
              </Box>
            ))
          : null}
      </Box>

      {phase === "counting" && mode === "count" && !loading ? (
        <OpsStickyActionBar
          sx={{
            position: "fixed",
            left: 0,
            right: 0,
            bottom: 0,
            px: 2,
            maxWidth: 420,
            mx: "auto",
            borderTop: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
          }}
        >
          <Button
            fullWidth
            variant="contained"
            disabled={submitting}
            onClick={handleSubmit}
            startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
            sx={{
              minHeight: 56,
              textTransform: "none",
              fontWeight: 900,
              fontSize: "1.05rem",
              borderRadius: `${OPS_MOBILE.radius.button}px`,
              bgcolor: OPS_MOBILE.cobalt,
            }}
          >
            {submitting ? "Submitting…" : "Submit Stock Check"}
          </Button>
        </OpsStickyActionBar>
      ) : null}
    </OpsMobileShell>
  );
}
