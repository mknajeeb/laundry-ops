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
  ItemCountCard,
  LoadingBlock,
  SearchField,
  SectionCard,
  StickyActionBar,
} from "./InventoryShared";
import { formatDateTime, groupItemsByCategory } from "../../utils/inventoryHelpers";

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
  const submitLockRef = useRef(false);
  const [started, setStarted] = useState(false);
  const [search, setSearch] = useState("");
  const [counts, setCounts] = useState({});
  const [notes, setNotes] = useState({});
  const [varianceReasons, setVarianceReasons] = useState({});
  const [threshold, setThreshold] = useState(varianceThreshold ?? 5);

  const weeklyItems = useMemo(() => {
    const base = (items || []).filter((i) => i.track_weekly_check !== false && i.is_active !== false);
    if (!search.trim()) return base;
    const q = search.toLowerCase();
    return base.filter((i) => (i.name || i.item_name || "").toLowerCase().includes(q) || (i.category_name || "").toLowerCase().includes(q));
  }, [items, search]);

  const grouped = useMemo(() => groupItemsByCategory(weeklyItems, categories), [weeklyItems, categories]);

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
        Object.values(draft.lines).forEach((ln) => {
          nextCounts[ln.item_id] = ln.counted_qty ?? "";
          nextNotes[ln.item_id] = ln.note ?? "";
          nextReasons[ln.item_id] = ln.variance_reason ?? "";
        });
        setCounts(nextCounts);
        setNotes(nextNotes);
        setVarianceReasons(nextReasons);
        if (Object.keys(nextCounts).length > 0) setStarted(true);
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

  const buildLines = () =>
    weeklyItems
      .filter((i) => counts[i.id] !== "" && counts[i.id] != null)
      .map((i) => ({
        item_id: i.id,
        counted_qty: parseFloat(counts[i.id]),
        note: notes[i.id] || null,
        variance_reason: varianceReasons[i.id] || null,
      }));

  const onSaveDraft = async () => {
    if (submitting) return;
    try {
      setSaving(true);
      await saveInventoryStockCheckDraft({ lines: buildLines(), notes: `Draft by ${displayName}` });
      onMessage?.({ type: "success", text: "Draft saved." });
      await loadDraft();
      onRefresh?.();
    } catch (e) {
      onMessage?.({ type: "error", text: e?.response?.data?.error || "Draft save failed." });
    } finally {
      setSaving(false);
    }
  };

  const onSubmit = async () => {
    if (submitting || submitLockRef.current) return;
    const lines = buildLines();
    if (lines.length === 0) {
      onMessage?.({ type: "error", text: "Enter at least one count before submitting." });
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
      setCounts({});
      setNotes({});
      setVarianceReasons({});
      setStarted(false);
      await onRefresh?.();
      onMessage?.({
        type: "success",
        text: `Weekly check submitted (${submitted} item${submitted === 1 ? "" : "s"} counted).`,
      });
      onGoDashboard?.();
    } catch (e) {
      const status = e?.response?.status;
      const err = e?.response?.data?.error || "Submit failed.";
      onMessage?.({
        type: "error",
        text: status === 409 ? err : err,
      });
    } finally {
      setSubmitting(false);
      submitLockRef.current = false;
    }
  };

  const submitLabel = submitting ? "Submitting…" : "Submit Weekly Check";
  const submitShortLabel = submitting ? "Submitting…" : "Submit";

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
            <SearchField value={search} onChange={setSearch} placeholder="Search items in this check…" />
            {grouped.map((cat, idx) => (
              <CategoryAccordion key={cat.id} category={cat} defaultExpanded={idx < 2}>
                {cat.items.map((item) => (
                  <ItemCountCard
                    key={item.id}
                    item={item}
                    countValue={counts[item.id] ?? ""}
                    noteValue={notes[item.id] ?? ""}
                    varianceReason={varianceReasons[item.id] ?? ""}
                    varianceThreshold={threshold}
                    onCountChange={(v) => setCounts((p) => ({ ...p, [item.id]: v }))}
                    onNoteChange={(v) => setNotes((p) => ({ ...p, [item.id]: v }))}
                    onVarianceReasonChange={(v) => setVarianceReasons((p) => ({ ...p, [item.id]: v }))}
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
