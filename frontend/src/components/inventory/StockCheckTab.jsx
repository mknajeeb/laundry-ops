import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import {
  getInventoryStockCheckDraft,
  saveInventoryStockCheckDraft,
  submitInventoryStockCheck,
} from "../../api";
import {
  CategoryAccordion,
  CategoryProgressBar,
  ItemCountCard,
  LoadingBlock,
  SearchField,
  SectionCard,
  StickyActionBar,
} from "./InventoryShared";
import { formatDateTime, groupItemsByCategory } from "../../utils/inventoryHelpers";

function itemIsDone(item, counts, statuses, recounts) {
  if (recounts[item.id]) return true;
  const isStatus = String(item.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
  if (isStatus) return Boolean(statuses[item.id]);
  return counts[item.id] !== "" && counts[item.id] != null;
}

export default function StockCheckTab({
  user,
  items,
  categories,
  latestCheck,
  varianceThreshold,
  onRefresh,
  onMessage,
  onGoDashboard,
}) {
  const displayName = user?.display_name || user?.username || "Unknown";
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [autosaveAt, setAutosaveAt] = useState(null);
  const submitLockRef = useRef(false);
  const autosaveTimerRef = useRef(null);
  const [started, setStarted] = useState(false);
  const [search, setSearch] = useState("");
  const [counts, setCounts] = useState({});
  const [notes, setNotes] = useState({});
  const [varianceReasons, setVarianceReasons] = useState({});
  const [statuses, setStatuses] = useState({});
  const [recounts, setRecounts] = useState({});
  const [threshold, setThreshold] = useState(varianceThreshold ?? 5);

  const weeklyItems = useMemo(() => {
    const base = (items || []).filter((i) => i.track_weekly_check !== false && i.is_active !== false);
    if (!search.trim()) return base;
    const q = search.toLowerCase();
    return base.filter((i) =>
      (i.name || i.item_name || "").toLowerCase().includes(q)
      || (i.category_name || "").toLowerCase().includes(q)
      || (i.sku || "").toLowerCase().includes(q)
      || (i.barcode || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const grouped = useMemo(() => groupItemsByCategory(weeklyItems, categories), [weeklyItems, categories]);

  const progressByCategory = useMemo(() => {
    return grouped.map((cat) => {
      const total = cat.items.length;
      const done = cat.items.filter((i) => itemIsDone(i, counts, statuses, recounts)).length;
      return { id: cat.id, name: cat.name, done, total };
    });
  }, [grouped, counts, statuses, recounts]);

  const overallDone = progressByCategory.reduce((s, c) => s + c.done, 0);
  const overallTotal = progressByCategory.reduce((s, c) => s + c.total, 0);

  const buildLines = useCallback(() => {
    return weeklyItems
      .map((i) => {
        const isStatus = String(i.tracking_mode || "QUANTITY").toUpperCase() === "STATUS";
        const needsRecount = Boolean(recounts[i.id]);
        if (isStatus) {
          const status = statuses[i.id];
          if (!status && !needsRecount) return null;
          return {
            item_id: i.id,
            status_level: status || i.status_level || "OK",
            counted_qty: null,
            note: notes[i.id] || null,
            variance_reason: null,
            needs_recount: needsRecount,
          };
        }
        if (needsRecount) {
          return {
            item_id: i.id,
            counted_qty: counts[i.id] === "" || counts[i.id] == null ? null : parseFloat(counts[i.id]),
            note: notes[i.id] || "Marked for recount",
            variance_reason: varianceReasons[i.id] || null,
            needs_recount: true,
          };
        }
        if (counts[i.id] === "" || counts[i.id] == null) return null;
        return {
          item_id: i.id,
          counted_qty: parseFloat(counts[i.id]),
          note: notes[i.id] || null,
          variance_reason: varianceReasons[i.id] || null,
          needs_recount: false,
        };
      })
      .filter(Boolean);
  }, [weeklyItems, counts, statuses, notes, varianceReasons, recounts]);

  const loadDraft = useCallback(async () => {
    try {
      setLoading(true);
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
        if (Object.keys(nextCounts).length > 0 || Object.keys(nextStatuses).length > 0) setStarted(true);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [varianceThreshold]);

  useEffect(() => {
    loadDraft();
  }, [loadDraft]);

  useEffect(() => {
    if (!started) return;
    setStatuses((prev) => {
      const next = { ...prev };
      let changed = false;
      weeklyItems.forEach((i) => {
        if (String(i.tracking_mode || "QUANTITY").toUpperCase() !== "STATUS") return;
        if (next[i.id]) return;
        next[i.id] = i.status_level || "OK";
        changed = true;
      });
      return changed ? next : prev;
    });
  }, [started, weeklyItems]);

  const persistDraft = useCallback(async (silent = true) => {
    if (submitting) return;
    try {
      if (!silent) setSaving(true);
      await saveInventoryStockCheckDraft({ lines: buildLines(), notes: `Draft by ${displayName}` });
      setAutosaveAt(new Date());
      if (!silent) onMessage?.({ type: "success", text: "Draft saved." });
    } catch (e) {
      if (!silent) onMessage?.({ type: "error", text: e?.response?.data?.error || "Draft save failed." });
    } finally {
      if (!silent) setSaving(false);
    }
  }, [buildLines, displayName, onMessage, submitting]);

  const scheduleAutosave = useCallback(() => {
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => {
      persistDraft(true);
    }, 450);
  }, [persistDraft]);

  useEffect(() => () => {
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
  }, []);

  const onSaveDraft = async () => {
    await persistDraft(false);
    await loadDraft();
    onRefresh?.();
  };

  const onSubmit = async () => {
    if (submitting || submitLockRef.current) return;
    const lines = buildLines();
    if (lines.length === 0) {
      onMessage?.({ type: "error", text: "Enter at least one count or status before submitting." });
      return;
    }
    submitLockRef.current = true;
    setSubmitting(true);
    try {
      const res = await submitInventoryStockCheck({
        lines,
        oneshot: true,
        notes: `Weekly check ${new Date().toISOString().slice(0, 10)}`,
      });
      const submitted = res?.data?.lines_submitted ?? lines.length;
      const recount = res?.data?.recount_flagged || 0;
      setCounts({});
      setNotes({});
      setVarianceReasons({});
      setStatuses({});
      setRecounts({});
      setStarted(false);
      await onRefresh?.();
      onMessage?.({
        type: "success",
        text: recount
          ? `Weekly check submitted (${submitted} lines, ${recount} marked for recount).`
          : `Weekly check submitted (${submitted} item${submitted === 1 ? "" : "s"} counted).`,
      });
      onGoDashboard?.();
    } catch (e) {
      const status = e?.response?.status;
      const err = e?.response?.data?.error || "Submit failed.";
      onMessage?.({ type: "error", text: status === 409 ? err : err });
    } finally {
      setSubmitting(false);
      submitLockRef.current = false;
    }
  };

  const submitLabel = submitting ? "Submitting…" : "Submit Weekly Check";
  const submitShortLabel = submitting ? "Submitting…" : "Submit";
  const autosaveLabel = autosaveAt ? `Saved ${autosaveAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "";

  if (loading && !started) return <LoadingBlock />;

  return (
    <Box sx={{ pb: { xs: 14, md: 2 } }}>
      <SectionCard
        title="Weekly Stock Check"
        subtitle={
          latestCheck?.submitted_at
            ? `Last checked by ${latestCheck.checked_by_name || displayName} on ${formatDateTime(latestCheck.submitted_at)}`
            : "Count what is on hand. Large differences require a reason."
        }
      >
        {!started ? (
          <Stack spacing={2}>
            <Button variant="contained" size="large" startIcon={<PlayArrowIcon />} onClick={() => setStarted(true)}>
              Start New Weekly Check
            </Button>
          </Stack>
        ) : (
          <>
            <SearchField value={search} onChange={setSearch} placeholder="Search items, SKU, barcode…" />
            {overallTotal > 0 ? (
              <Box sx={{ mb: 2 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                  <Typography variant="body2" fontWeight={700}>Progress</Typography>
                  {autosaveLabel ? (
                    <Typography variant="caption" color="success.main">{autosaveLabel}</Typography>
                  ) : null}
                </Stack>
                <CategoryProgressBar label="Overall" done={overallDone} total={overallTotal} />
                {progressByCategory.map((c) => (
                  <CategoryProgressBar key={c.id} label={c.name} done={c.done} total={c.total} />
                ))}
              </Box>
            ) : null}
            {grouped.map((cat, idx) => (
              <CategoryAccordion key={cat.id} category={cat} defaultExpanded={idx < 2}>
                {cat.items.map((item) => (
                  <ItemCountCard
                    key={item.id}
                    item={item}
                    countValue={counts[item.id] ?? ""}
                    noteValue={notes[item.id] ?? ""}
                    varianceReason={varianceReasons[item.id] ?? ""}
                    statusValue={statuses[item.id] ?? item.status_level ?? "OK"}
                    needsRecount={Boolean(recounts[item.id])}
                    varianceThreshold={threshold}
                    onCountChange={(v) => {
                      setCounts((p) => ({ ...p, [item.id]: v }));
                      scheduleAutosave();
                    }}
                    onNoteChange={(v) => {
                      setNotes((p) => ({ ...p, [item.id]: v }));
                      scheduleAutosave();
                    }}
                    onVarianceReasonChange={(v) => {
                      setVarianceReasons((p) => ({ ...p, [item.id]: v }));
                      scheduleAutosave();
                    }}
                    onStatusChange={(v) => {
                      setStatuses((p) => ({ ...p, [item.id]: v }));
                      scheduleAutosave();
                    }}
                    onRecountChange={(v) => {
                      setRecounts((p) => ({ ...p, [item.id]: Boolean(v) }));
                      scheduleAutosave();
                    }}
                  />
                ))}
              </CategoryAccordion>
            ))}
            <Stack direction="row" spacing={1.5} justifyContent="flex-end" sx={{ mt: 2, display: { xs: "none", md: "flex" } }}>
              <Button variant="outlined" onClick={onSaveDraft} disabled={saving || submitting}>Save Draft</Button>
              <Button
                variant="contained"
                onClick={onSubmit}
                disabled={saving || submitting}
                startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
              >
                {submitLabel}
              </Button>
            </Stack>
          </>
        )}
      </SectionCard>
      {started ? (
        <StickyActionBar>
          <Button fullWidth variant="outlined" onClick={onSaveDraft} disabled={saving || submitting}>Save Draft</Button>
          <Button
            fullWidth
            variant="contained"
            onClick={onSubmit}
            disabled={saving || submitting}
            startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : null}
          >
            {submitShortLabel}
          </Button>
        </StickyActionBar>
      ) : null}
    </Box>
  );
}
