import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  getDrcMobileToday,
  putDrcMobileSectionDraft,
  submitDrcMobileAll,
} from "../api";
import OpsMobileShell from "./OpsMobileShell";
import OpsStickyActionBar from "./OpsStickyActionBar";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import { createStockSubmitController } from "./createStockDraftAutosave";
import { createFloorRevisionedAutosave } from "./createFloorRevisionedAutosave";
import {
  allSectionsSubmitted,
  compactProgress,
  DRC_MOBILE_CONFLICT_MESSAGE,
  formatBusinessDateLong,
  formatMoneyInput,
  formatSubmittedTime,
  parseMoneyInput,
  parseQtyInput,
  sectionIsLocked,
  sectionIsReturned,
  valuesStateFromPayload,
} from "../utils/drcMobileEntryHelpers";

/** Prominent business date from mobile API payload — not browser "today". */
function BusinessDateHeading({ businessDate }) {
  const label = formatBusinessDateLong(businessDate);
  if (!label) return null;
  return (
    <Typography
      component="h2"
      sx={{
        fontWeight: 800,
        fontSize: "1.15rem",
        lineHeight: 1.3,
        color: OPS_MOBILE.navy,
        mt: 0.5,
        mb: 0.25,
      }}
    >
      {label}
    </Typography>
  );
}

/**
 * Phase 5E dedicated mobile Revenue & Cost — never loads manager Finance dashboard.
 */
export default function RevenueCostFloorFlow({ onBack, onDone, onLock }) {
  const [phase, setPhase] = useState("loading"); // loading | entry | review | submitted | empty
  const [payload, setPayload] = useState(null);
  const [valuesState, setValuesState] = useState({});
  const [fieldErrors, setFieldErrors] = useState({});
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState(""); // '' | saving | saved | error | conflict
  const [conflictSection, setConflictSection] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const stateRef = useRef({});
  const autosavesRef = useRef({});
  const submitRef = useRef(null);
  stateRef.current = { valuesState, phase, submitting, payload, saveState };

  const applySectionRevision = useCallback((sectionKey, data) => {
    if (!data) return;
    setPayload((prev) => {
      if (!prev) return prev;
      const nextSecs = (prev.assigned_sections || []).map((s) =>
        s.section_key === sectionKey
          ? { ...s, ...data, values: s.values /* keep local via valuesState */ }
          : s,
      );
      return { ...prev, assigned_sections: nextSecs };
    });
    setValuesState((prev) => {
      const cur = prev[sectionKey] || {};
      return {
        ...prev,
        [sectionKey]: {
          ...cur,
          draft_revision: Number(data.draft_revision) || 0,
          status: String(data.status || cur.status || "draft").toLowerCase(),
          rejection_reason: data.rejection_reason ?? cur.rejection_reason,
          calculated: data.calculated || cur.calculated,
          submitted_at: data.submitted_at || cur.submitted_at,
          fields: data.fields || cur.fields,
          section_label: data.section_label || cur.section_label,
        },
      };
    });
  }, []);

  const ensureAutosave = useCallback(
    (sectionKey) => {
      if (autosavesRef.current[sectionKey]) return autosavesRef.current[sectionKey];
      const ctrl = createFloorRevisionedAutosave({
        debounceMs: 450,
        buildPayload: ({ expected_revision }) => {
          const sec = stateRef.current.valuesState[sectionKey] || {};
          return {
            values: sec.values || {},
            note: sec.note || "",
            expected_revision,
            entry_date: stateRef.current.payload?.business_date,
          };
        },
        getExpectedRevision: () =>
          Number(stateRef.current.valuesState[sectionKey]?.draft_revision) || 0,
        isBlocked: () =>
          stateRef.current.submitting ||
          sectionIsLocked(stateRef.current.valuesState[sectionKey]?.status),
        saveDraft: async (body) => {
          setSaveState("saving");
          const res = await putDrcMobileSectionDraft(sectionKey, body);
          return res?.data;
        },
        onSaved: (data) => {
          applySectionRevision(sectionKey, data);
          setSaveState("saved");
          setError("");
          setConflictSection(null);
        },
        onError: (msg) => {
          setSaveState("error");
          setError(msg || "Couldn’t save. Try again.");
        },
        onConflict: async () => {
          setSaveState("conflict");
          setConflictSection(sectionKey);
          setError(DRC_MOBILE_CONFLICT_MESSAGE);
          try {
            const res = await getDrcMobileToday();
            const data = res?.data || {};
            const remote = (data.assigned_sections || []).find(
              (s) => s.section_key === sectionKey,
            );
            if (remote) {
              // Refresh revision only — preserve local field values.
              applySectionRevision(sectionKey, remote);
            }
          } catch {
            /* keep local */
          }
        },
      });
      autosavesRef.current[sectionKey] = ctrl;
      return ctrl;
    },
    [applySectionRevision],
  );

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const res = await getDrcMobileToday();
      const data = res?.data || {};
      setPayload(data);
      stateRef.current.payload = data;
      const vs = valuesStateFromPayload(data);
      setValuesState(vs);
      if (!(data.assigned_sections || []).length) {
        setPhase("empty");
      } else if (allSectionsSubmitted(data)) {
        setPhase("submitted");
      } else {
        setPhase("entry");
      }
    } catch (e) {
      setLoadError(e?.response?.data?.error || e?.message || "Could not load Revenue & Cost");
      setPhase("empty");
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      Object.values(autosavesRef.current).forEach((c) => c.dispose?.());
      autosavesRef.current = {};
    };
  }, [load]);

  useEffect(() => {
    submitRef.current = createStockSubmitController({
      // Guard only — DRC payload is section-scoped, not stock lines.
      buildLines: () => [{ section: true }],
      isBlocked: () =>
        stateRef.current.phase === "submitted" || stateRef.current.phase === "empty",
      submitCheck: async () => {
        for (const c of Object.values(autosavesRef.current)) {
          if (c.hasConflict?.()) {
            const err = new Error(DRC_MOBILE_CONFLICT_MESSAGE);
            err.response = { status: 409, data: { error: DRC_MOBILE_CONFLICT_MESSAGE } };
            throw err;
          }
          await c.flushNow?.();
        }
        return submitDrcMobileAll({
          entry_date: stateRef.current.payload?.business_date,
        });
      },
      onSuccess: (res) => {
        const data = res?.data || {};
        setPayload(data);
        setValuesState(valuesStateFromPayload(data));
        setPhase("submitted");
        setError("");
        setSaveState("");
      },
      onError: (msg) => setError(msg || "Couldn’t submit. Try again."),
    });
  }, []);

  const progress = useMemo(() => compactProgress(valuesState), [valuesState]);

  const setFieldValue = (sectionKey, fieldKey, kind, raw) => {
    const parsed = kind === "money" ? parseMoneyInput(raw) : parseQtyInput(raw);
    setFieldErrors((prev) => {
      const next = { ...prev };
      const ek = `${sectionKey}.${fieldKey}`;
      if (!parsed.ok) next[ek] = parsed.error;
      else delete next[ek];
      return next;
    });
    setValuesState((prev) => {
      const sec = prev[sectionKey] || { values: {} };
      return {
        ...prev,
        [sectionKey]: {
          ...sec,
          values: {
            ...sec.values,
            [fieldKey]: parsed.ok ? parsed.value : sec.values?.[fieldKey],
          },
        },
      };
    });
    if (parsed.ok) {
      ensureAutosave(sectionKey).schedule();
    }
  };

  const retryConflict = async () => {
    if (!conflictSection) return;
    const ctrl = autosavesRef.current[conflictSection];
    ctrl?.clearConflict?.();
    setSaveState("saving");
    setError("");
    const result = await ctrl?.flushNow?.();
    if (result?.conflict) {
      setSaveState("conflict");
      setError(DRC_MOBILE_CONFLICT_MESSAGE);
    }
  };

  const goReview = async () => {
    setError("");
    for (const c of Object.values(autosavesRef.current)) {
      if (c.hasConflict?.()) {
        setSaveState("conflict");
        setError(DRC_MOBILE_CONFLICT_MESSAGE);
        return;
      }
      await c.flushNow?.();
    }
    const errs = {};
    for (const [sk, sec] of Object.entries(valuesState)) {
      if (sectionIsLocked(sec.status)) continue;
      for (const f of sec.fields || []) {
        if (!f.required || f.kind === "info") continue;
        const v = sec.values?.[f.key];
        if (v === null || v === undefined || v === "") {
          errs[`${sk}.${f.key}`] = "Required";
        }
      }
    }
    if (Object.keys(errs).length) {
      setFieldErrors(errs);
      setError("Complete all assigned fields before review.");
      return;
    }
    setPhase("review");
  };

  const doSubmit = async () => {
    if (submitting || submitRef.current?.isPending?.()) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await submitRef.current?.submit?.();
      if (result?.conflict || Number(result?.error?.response?.status) === 409) {
        setSaveState("conflict");
        setError(DRC_MOBILE_CONFLICT_MESSAGE);
      } else if (result?.reason === "pending") {
        setError("Submit already in progress.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const saveLabel =
    saveState === "saving"
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "conflict"
          ? "Conflict"
          : saveState === "error"
            ? "Save failed"
            : "";

  if (phase === "loading") {
    return (
      <OpsMobileShell>
        <OpsTopBar title="Revenue & Cost" onBack={onBack} onLock={onLock} />
        <Box sx={{ py: 6, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      </OpsMobileShell>
    );
  }

  if (phase === "submitted") {
    const first = (payload?.assigned_sections || [])[0];
    return (
      <OpsMobileShell>
        <OpsTopBar title="Revenue & Cost" onBack={onBack} onLock={onLock} />
        <BusinessDateHeading businessDate={payload?.business_date} />
        <Stack spacing={1.5} sx={{ py: 4, px: 1, textAlign: "center" }}>
          <Typography fontWeight={800} sx={{ fontSize: "1.15rem" }}>
            Revenue & Cost Submitted
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.85rem" }}>
            Pending manager review
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {formatSubmittedTime(first?.submitted_at)}
          </Typography>
          <Button
            variant="contained"
            onClick={onDone}
            sx={{ mt: 2, textTransform: "none", fontWeight: 800 }}
          >
            Done
          </Button>
          <Button onClick={onLock} sx={{ textTransform: "none" }}>
            Lock
          </Button>
        </Stack>
      </OpsMobileShell>
    );
  }

  if (phase === "empty") {
    return (
      <OpsMobileShell>
        <OpsTopBar title="Revenue & Cost" onBack={onBack} onLock={onLock} />
        <BusinessDateHeading businessDate={payload?.business_date} />
        <Alert severity="info" sx={{ mt: 2 }}>
          {loadError || "No Revenue & Cost entry assigned today."}
        </Alert>
      </OpsMobileShell>
    );
  }

  return (
    <OpsMobileShell>
      <OpsTopBar title="Revenue & Cost" onBack={onBack} onLock={onLock} />
      <BusinessDateHeading businessDate={payload?.business_date} />
      <Stack spacing={1} sx={{ pb: 10 }}>
        <Typography variant="body2" color="text.secondary" sx={{ fontSize: "0.85rem" }}>
          {[
            progress.total ? `${progress.done}/${progress.total} sections` : "",
            saveLabel || "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </Typography>

        {error ? (
          <Alert
            severity={saveState === "conflict" ? "warning" : "error"}
            action={
              saveState === "conflict" ? (
                <Button color="inherit" size="small" onClick={retryConflict}>
                  Retry
                </Button>
              ) : null
            }
            onClose={() => setError("")}
          >
            {error}
          </Alert>
        ) : null}

        {phase === "entry"
          ? Object.entries(valuesState).map(([sectionKey, sec]) => {
              const locked = sectionIsLocked(sec.status);
              const returned = sectionIsReturned(sec.status);
              const returnReason = sec.return_reason || sec.rejection_reason;
              return (
                <Box
                  key={sectionKey}
                  sx={{
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 2,
                    p: 1.5,
                  }}
                >
                  <Typography fontWeight={800} sx={{ fontSize: "0.95rem", mb: 0.75 }}>
                    {sec.section_label || sectionKey}
                    {String(sec.status) === "approved"
                      ? " · Approved"
                      : locked
                        ? " · Submitted (pending review)"
                        : returned
                          ? " · Returned"
                          : ""}
                  </Typography>
                  {returned && returnReason ? (
                    <Alert severity="warning" sx={{ mb: 1, py: 0.5 }}>
                      Returned for correction: {returnReason}
                    </Alert>
                  ) : null}
                  <Stack spacing={1}>
                    {(sec.fields || [])
                      .filter((f) => f.kind !== "info")
                      .map((f) => {
                        const ek = `${sectionKey}.${f.key}`;
                        const display =
                          f.kind === "money" &&
                          sec.values?.[f.key] !== null &&
                          sec.values?.[f.key] !== undefined &&
                          sec.values?.[f.key] !== ""
                            ? String(sec.values[f.key])
                            : sec.values?.[f.key] ?? "";
                        return (
                          <TextField
                            key={f.key}
                            size="small"
                            label={f.label}
                            value={display === null || display === undefined ? "" : display}
                            disabled={locked || submitting}
                            error={Boolean(fieldErrors[ek])}
                            helperText={
                              fieldErrors[ek] ||
                              (f.kind === "money" && sec.values?.[f.key] != null
                                ? formatMoneyInput(sec.values[f.key])
                                : " ")
                            }
                            inputProps={{
                              inputMode: "decimal",
                              pattern: "[0-9]*\\.?[0-9]*",
                            }}
                            onChange={(e) =>
                              setFieldValue(sectionKey, f.key, f.kind, e.target.value)
                            }
                            fullWidth
                          />
                        );
                      })}
                    <TextField
                      size="small"
                      label="Note (optional)"
                      value={sec.note || ""}
                      disabled={locked || submitting}
                      onChange={(e) => {
                        const note = e.target.value.slice(0, 500);
                        setValuesState((prev) => ({
                          ...prev,
                          [sectionKey]: { ...prev[sectionKey], note },
                        }));
                        ensureAutosave(sectionKey).schedule();
                      }}
                      fullWidth
                      multiline
                      minRows={1}
                    />
                  </Stack>
                </Box>
              );
            })
          : null}

        {phase === "review" ? (
          <Box>
            <Typography fontWeight={800} sx={{ mb: 1 }}>
              Review before submit
            </Typography>
            <Stack spacing={1.25}>
              {Object.entries(valuesState).map(([sectionKey, sec]) => (
                <Box
                  key={sectionKey}
                  sx={{ border: "1px solid", borderColor: "divider", borderRadius: 2, p: 1.25 }}
                >
                  <Typography fontWeight={700} sx={{ fontSize: "0.9rem", mb: 0.5 }}>
                    {sec.section_label}
                  </Typography>
                  {(sec.fields || [])
                    .filter((f) => f.kind !== "info")
                    .map((f) => (
                      <Typography key={f.key} variant="body2" sx={{ fontSize: "0.85rem" }}>
                        {f.label}:{" "}
                        {f.kind === "money"
                          ? formatMoneyInput(sec.values?.[f.key] ?? 0)
                          : sec.values?.[f.key] ?? 0}
                      </Typography>
                    ))}
                  {sec.note ? (
                    <Typography variant="caption" color="text.secondary">
                      Note: {sec.note}
                    </Typography>
                  ) : null}
                </Box>
              ))}
            </Stack>
          </Box>
        ) : null}
      </Stack>

      <OpsStickyActionBar>
        {phase === "entry" ? (
          <Button
            fullWidth
            variant="contained"
            disabled={submitting || saveState === "conflict"}
            onClick={goReview}
            sx={{ textTransform: "none", fontWeight: 800 }}
          >
            Review
          </Button>
        ) : null}
        {phase === "review" ? (
          <Stack direction="row" spacing={1} sx={{ width: "100%" }}>
            <Button
              fullWidth
              variant="outlined"
              disabled={submitting}
              onClick={() => setPhase("entry")}
              sx={{ textTransform: "none" }}
            >
              Back
            </Button>
            <Button
              fullWidth
              variant="contained"
              disabled={submitting || saveState === "conflict"}
              onClick={doSubmit}
              sx={{ textTransform: "none", fontWeight: 800 }}
            >
              {submitting ? "Submitting…" : "Submit"}
            </Button>
          </Stack>
        ) : null}
      </OpsStickyActionBar>
    </OpsMobileShell>
  );
}
