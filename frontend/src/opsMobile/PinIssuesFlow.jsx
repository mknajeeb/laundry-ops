import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import AddAPhotoOutlinedIcon from "@mui/icons-material/AddAPhotoOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CloseIcon from "@mui/icons-material/Close";
import LostFoundReportForm from "../components/lostFound/LostFoundReportForm";
import {
  getIssuesRegister,
  getLostFoundItem,
  getLostFoundLocations,
  getLostFoundPhoto,
  getManagementIssue,
  patchManagementIssue,
  postLostFoundReport,
  updateLostFoundStatus,
} from "../api";
import { useI18n } from "../i18n/I18nContext";
import { businessTodayYmd } from "../utils/businessTime";
import { reportFailureMessage, savedReport } from "../utils/lostFoundSubmit";
import { formatFriendlyEtWall } from "../utils/rinseTimeFormat";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";
import {
  canGoNext,
  isClosedStatus,
  loadPinIssuesView,
  rangeFor,
  rangeLabel,
  savePinIssuesView,
  shiftRange,
  statusesForIssue,
} from "./pinIssuesRange";
import { reportKeyFromSearch } from "./pinIssuesDeepLink";

const STATUS_COLOR = {
  open: "#b45309",
  new: "#b45309",
  review: "#1d4ed8",
  under_review: "#1d4ed8",
  investigating: "#1d4ed8",
  resolved: "#0f766e",
  returned: "#0f766e",
  stored: "#475569",
  excluded: "#475569",
};

const TYPE_OPTIONS = [
  ["", "issues.filter.allTypes"],
  ["orphan", "lostFound.foundTitle"],
  ["redry", "lostFound.redryTitle"],
  ["equipment", "lostFound.equipmentTitle"],
  ["MISSING", "issues.type.missing"],
  ["DAMAGE", "issues.type.damage"],
  ["RECLEAN", "issues.type.reclean"],
  ["MIXED_CUSTOMER_ITEMS", "issues.type.mixed"],
  ["REJECTED", "issues.type.rejected"],
  ["FOUND", "issues.type.found"],
  ["QUALITY", "issues.type.quality"],
  ["OTHER", "issues.type.other"],
];

function statusColor(code) {
  return STATUS_COLOR[String(code || "").toLowerCase()] || OPS_MOBILE.navy;
}

function sourceLabel(source, t) {
  return source === "employee" ? t("issues.source.employee") : t("issues.source.customer");
}

function placeLabel(row) {
  return row?.location || row?.order_reference || row?.customer_name || "—";
}

function CountButton({ label, value, selected, color, onClick }) {
  return (
    <Button
      onClick={onClick}
      aria-pressed={selected}
      sx={{
        flex: "1 1 0",
        minWidth: 0,
        minHeight: 58,
        px: 0.75,
        py: 0.6,
        borderRadius: "14px",
        textTransform: "none",
        justifyContent: "flex-start",
        alignItems: "flex-start",
        bgcolor: selected ? alpha(color, 0.14) : "#fff",
        border: `1.5px solid ${selected ? color : alpha(OPS_MOBILE.navy, 0.08)}`,
        boxShadow: "none",
      }}
    >
      <Box sx={{ textAlign: "left", minWidth: 0 }}>
        <Typography sx={{ fontSize: 11, fontWeight: 800, color: OPS_MOBILE.muted, lineHeight: 1.15 }}>
          {label}
        </Typography>
        <Typography sx={{ fontSize: 22, fontWeight: 900, color, lineHeight: 1.15 }}>{value}</Typography>
      </Box>
    </Button>
  );
}

function IssueCard({ row, onOpen, t }) {
  const group = row.status_group || "open";
  const color = statusColor(group === "review" ? "under_review" : group === "open" ? "open" : row.status);
  return (
    <Button
      fullWidth
      onClick={() => onOpen(row)}
      sx={{
        display: "block",
        textAlign: "left",
        textTransform: "none",
        color: OPS_MOBILE.navy,
        bgcolor: "#fff",
        borderRadius: "16px",
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
        borderLeft: `4px solid ${color}`,
        px: 1.25,
        py: 1,
        minHeight: 0,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 800, fontSize: "0.92rem", lineHeight: 1.25 }}>
            {row.employee_name || t("issues.unknownEmployee")}
          </Typography>
          <Typography sx={{ fontSize: "0.78rem", color: OPS_MOBILE.muted, fontWeight: 650 }}>
            {formatFriendlyEtWall(row.reported_at || row.business_date)}
          </Typography>
        </Box>
        <Box
          sx={{
            flexShrink: 0,
            px: 0.8,
            py: 0.25,
            borderRadius: 99,
            bgcolor: alpha(color, 0.12),
            color,
            fontSize: 11,
            fontWeight: 800,
          }}
        >
          {t(`issues.status.${row.status}`)}
        </Box>
      </Stack>
      <Typography sx={{ mt: 0.45, fontWeight: 750, fontSize: "0.86rem" }}>{row.category_label}</Typography>
      <Typography sx={{ fontSize: "0.78rem", color: OPS_MOBILE.muted }}>
        {sourceLabel(row.source, t)} · {placeLabel(row)}
        {row.photo_count ? ` · ${t("issues.photos", { count: row.photo_count })}` : ""}
      </Typography>
      {row.summary ? (
        <Typography
          sx={{
            mt: 0.35,
            fontSize: "0.82rem",
            lineHeight: 1.3,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {row.summary}
        </Typography>
      ) : null}
    </Button>
  );
}

function useIssuePhotos(photos) {
  const [urls, setUrls] = useState([]);
  const photoKey = JSON.stringify((photos || []).map((photo) => [photo?.id || "", photo?.url || ""]));
  useEffect(() => {
    const list = JSON.parse(photoKey).map(([id, url]) => ({ id, url }));
    let cancelled = false;
    const created = [];
    const ready = list.filter((photo) => photo.url).map((photo) => ({ id: photo.id, url: photo.url }));
    (async () => {
      const next = [...ready];
      for (const photo of list) {
        if (!photo.id || photo.url) continue;
        try {
          const res = await getLostFoundPhoto(photo.id);
          if (cancelled) return;
          if (res?.data instanceof Blob && res.data.size > 8 && String(res.data.type || "").startsWith("image/")) {
            const url = URL.createObjectURL(res.data);
            created.push(url);
            next.push({ id: photo.id, url });
          }
        } catch {
          /* one photo can fail without hiding the rest */
        }
      }
      if (!cancelled) setUrls(next);
    })();
    return () => {
      cancelled = true;
      created.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [photoKey]);
  return urls;
}

export default function PinIssuesFlow({ onBack, onLock, preview = null }) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const linkedReport = reportKeyFromSearch(searchParams.toString());
  const today = businessTodayYmd();
  const saved = useMemo(() => loadPinIssuesView(), []);
  const [range, setRange] = useState(() =>
    rangeFor(saved?.mode, saved?.anchor, saved?.from, saved?.to, today),
  );
  const [statusGroup, setStatusGroup] = useState(saved?.statusGroup || "");
  const [source, setSource] = useState(saved?.source || "all");
  const [category, setCategory] = useState(saved?.category || "");
  const [employee, setEmployee] = useState(saved?.employee || "");
  const [q, setQ] = useState(saved?.q || "");
  const [sort, setSort] = useState(saved?.sort || "newest");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState(linkedReport || saved?.detailKey ? "detail" : "list");
  const [detailKey, setDetailKey] = useState(linkedReport || saved?.detailKey || "");
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [remarks, setRemarks] = useState("");
  const [reason, setReason] = useState("");
  const [orderRef, setOrderRef] = useState("");
  const [saving, setSaving] = useState(false);
  const [zoom, setZoom] = useState("");
  const [reportChoices, setReportChoices] = useState(null);
  const [reportError, setReportError] = useState("");
  const [reportDone, setReportDone] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const saveLock = useRef(false);

  useEffect(() => {
    savePinIssuesView({
      mode: range.mode,
      anchor: range.anchor,
      from: range.from,
      to: range.to,
      statusGroup,
      source,
      category,
      employee,
      q,
      sort,
      detailKey: view === "detail" ? detailKey : "",
    });
  }, [range, statusGroup, source, category, employee, q, sort, view, detailKey]);

  const load = useCallback(
    async (nextPage = 1) => {
      if (nextPage === 1) setLoading(true);
      else setLoadingMore(true);
      setError("");
      try {
        const { data } = await getIssuesRegister({
          date_from: range.from,
          date_to: range.to,
          source,
          category: category || undefined,
          status_group: statusGroup || undefined,
          employee: employee || undefined,
          q: q || undefined,
          sort,
          page: nextPage,
          page_size: 100,
        });
        if (data?.error && !data?.ok) throw new Error(data.error);
        const incoming = data?.rows || [];
        setRows((prev) => (nextPage === 1 ? incoming : [...prev, ...incoming]));
        setSummary(data?.summary || null);
        setTotal(Number(data?.total || 0));
        setPage(nextPage);
      } catch (err) {
        setError(err?.response?.data?.error || err.message || t("issues.loadFailed"));
        if (nextPage === 1) {
          setRows([]);
          setSummary(null);
        }
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [category, employee, q, range.from, range.to, sort, source, statusGroup, t],
  );

  useEffect(() => {
    if (preview) {
      setRows(preview.rows || []);
      setSummary(preview.summary || null);
      setTotal((preview.rows || []).length);
      setLoading(false);
      setError("");
      return undefined;
    }
    const timer = setTimeout(() => load(1), 180);
    return () => clearTimeout(timer);
  }, [load, preview]);

  const openDetail = useCallback(
    async (row) => {
      const key = row?.key || "";
      setView("detail");
      setDetailKey(key);
      setDetail(null);
      setDetailError("");
      setDetailLoading(true);
      setRemarks("");
      setReason("");
      setZoom("");
      try {
        const sample = preview?.details?.[row.key];
        if (sample) {
          setDetail(sample);
          setRemarks(sample.issue?.internal_notes || sample.item?.status_comment || "");
          setOrderRef(sample.item?.order_reference || sample.issue?.bag_id || "");
          setReason(sample.item?.resolved_reason || "");
          return;
        }
        if (row.source === "rinse") {
          const { data } = await getManagementIssue(row.source_id, { events: 1 });
          if (data?.error) throw new Error(data.error);
          setDetail({ source: "rinse", row, issue: data.issue, events: data.events || [] });
          setRemarks(data.issue?.internal_notes || "");
          setOrderRef(data.issue?.order_display_id || data.issue?.bag_id || row.order_reference || "");
        } else {
          const { data } = await getLostFoundItem(row.source_id);
          if (!data?.ok) throw new Error(data?.error || t("issues.openFailed"));
          setDetail({ source: "employee", row, item: data.item, events: data.item?.events || [] });
          setRemarks(data.item?.status_comment || "");
          setOrderRef(data.item?.order_reference || "");
          setReason(data.item?.resolved_reason || "");
        }
      } catch (err) {
        setDetailError(err?.response?.data?.error || err.message || t("issues.openFailed"));
      } finally {
        setDetailLoading(false);
      }
    },
    [preview, t],
  );

  const restoredDetail = useRef(false);
  useEffect(() => {
    if (restoredDetail.current || view !== "detail" || !detailKey) return undefined;
    restoredDetail.current = true;
    const [sourceName, id] = String(detailKey).split(":");
    if (!sourceName || !id) return undefined;
    openDetail({ key: detailKey, source: sourceName, source_id: Number(id) });
    return undefined;
  }, [detailKey, openDetail, view]);

  const photos = useIssuePhotos(detail?.item?.photos);

  const applyStatus = async (nextStatus) => {
    if (saveLock.current || !detail) return;
    if (preview) {
      setDetail((prev) => {
        if (!prev) return prev;
        if (prev.source === "rinse") {
          return { ...prev, issue: { ...prev.issue, status: nextStatus, internal_notes: remarks } };
        }
        return {
          ...prev,
          item: { ...prev.item, status: nextStatus, status_comment: remarks, resolved_reason: reason },
        };
      });
      return;
    }
    const currentStatus = detail.source === "rinse" ? detail.issue?.status : detail.item?.status;
    const note = remarks.trim();
    if (nextStatus === currentStatus && !note && !(nextStatus === "resolved" && reason.trim())) return;
    if (nextStatus === "returned" && orderRef.trim().length < 1) {
      setDetailError(t("issues.orderRequired"));
      return;
    }
    if (nextStatus === "returned" && note.length < 2) {
      setDetailError(t("issues.commentRequired"));
      return;
    }
    if (nextStatus === "resolved" && detail.source === "employee" && reason.trim().length < 3) {
      setDetailError(t("issues.reasonRequired"));
      return;
    }
    saveLock.current = true;
    setSaving(true);
    setDetailError("");
    try {
      if (detail.source === "rinse") {
        const body = {};
        if (nextStatus && nextStatus !== currentStatus) body.status = nextStatus;
        if (note !== String(detail.issue?.internal_notes || "").trim()) body.internal_notes = note;
        if (nextStatus === "resolved") body.resolution_notes = note || detail.issue?.resolution_notes || "";
        if (!Object.keys(body).length) return;
        const { data } = await patchManagementIssue(detail.issue.id, body);
        if (data?.error) throw new Error(data.error);
      } else {
        const res = await updateLostFoundStatus(detail.item.id, {
          status: nextStatus || currentStatus,
          comment: note,
          reason: nextStatus === "resolved" ? reason.trim() : "",
          order_reference: orderRef.trim(),
        });
        if (!res?.data?.ok) throw new Error(res?.data?.error || t("issues.saveFailed"));
      }
      await openDetail(detail.row || { key: detailKey, source: detail.source, source_id: detail.issue?.id || detail.item?.id });
      load(1);
    } catch (err) {
      setDetailError(err?.response?.data?.error || err.message || t("issues.saveFailed"));
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  };

  const startReport = async () => {
    setView("create");
    setReportError("");
    setReportDone(null);
    if (reportChoices) return;
    try {
      const res = await getLostFoundLocations();
      if (res?.data?.ok) setReportChoices(res.data);
    } catch (err) {
      setReportError(t("issues.locationsFailed"));
    }
  };

  const submitReport = async (payload) => {
    if (saveLock.current) return;
    saveLock.current = true;
    setSaving(true);
    setReportError("");
    try {
      const res = await postLostFoundReport(payload);
      const saved = savedReport(res?.data || {});
      if (!saved) {
        throw new Error(reportFailureMessage(res?.data, t("lostFound.saveFailed")));
      }
      setReportDone(saved);
      load(1);
    } catch (err) {
      const data = err?.response?.data;
      setReportError(reportFailureMessage(data, "") || err.message || t("lostFound.saveFailed"));
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  };

  const current = detail?.source === "rinse" ? detail.issue : detail?.item;
  const currentStatus = current?.status || "";
  const allowedStatuses = statusesForIssue(
    detail?.source === "rinse"
      ? { source: "rinse" }
      : { source: "employee", category: detail?.item?.report_category || detail?.row?.category },
  );

  const nav = (
    <Box
      sx={{
        px: 0.4,
        py: 0.4,
        borderRadius: "16px",
        bgcolor: alpha("#fff", 0.94),
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
      }}
    >
      <Stack direction="row" spacing={0.5} sx={{ mb: 0.4 }}>
        {[
          ["day", "issues.mode.day"],
          ["week", "issues.mode.week"],
          ["custom", "issues.mode.range"],
        ].map(([mode, key]) => (
          <Button
            key={mode}
            onClick={() => setRange(rangeFor(mode, range.anchor || today, range.from, range.to, today))}
            sx={{
              flex: 1,
              minHeight: 36,
              textTransform: "none",
              fontWeight: 800,
              fontSize: "0.82rem",
              borderRadius: "12px",
              color: range.mode === mode ? "#fff" : OPS_MOBILE.navy,
              bgcolor: range.mode === mode ? OPS_MOBILE.blue : "transparent",
            }}
          >
            {t(key)}
          </Button>
        ))}
      </Stack>
      <Stack direction="row" alignItems="center" spacing={0.25}>
        <IconButton
          aria-label={t("issues.prev")}
          onClick={() => setRange((prev) => shiftRange(prev, -1, today))}
          sx={{ minWidth: 44, minHeight: 44 }}
        >
          <ChevronLeftIcon />
        </IconButton>
        <Box sx={{ flex: 1, textAlign: "center", minWidth: 0 }}>
          <Typography sx={{ fontWeight: 900, fontSize: "0.98rem", lineHeight: 1.2 }}>
            {range.mode === "day" && range.from === today
              ? t("issues.today")
              : range.mode === "day" && rangeLabel(range, today) === "Yesterday"
                ? t("issues.yesterday")
                : rangeLabel(range, today)}
          </Typography>
          <Typography sx={{ fontSize: 11, color: OPS_MOBILE.muted, fontWeight: 700 }}>
            {range.from === range.to ? range.from : `${range.from} – ${range.to}`} ET
          </Typography>
        </Box>
        <IconButton
          aria-label={t("issues.next")}
          disabled={!canGoNext(range, today)}
          onClick={() => setRange((prev) => shiftRange(prev, 1, today))}
          sx={{ minWidth: 44, minHeight: 44 }}
        >
          <ChevronRightIcon />
        </IconButton>
      </Stack>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ px: 0.5, pb: 0.4 }}>
        <Button
          onClick={() => setRange(rangeFor("day", today, today, today, today))}
          disabled={range.mode === "day" && range.from === today}
          sx={{ textTransform: "none", fontWeight: 800, minHeight: 36 }}
        >
          {t("issues.today")}
        </Button>
        <TextField
          type="date"
          size="small"
          value={range.anchor || range.from}
          inputProps={{ max: today, "aria-label": t("issues.pickDate") }}
          onChange={(e) => {
            const value = e.target.value;
            if (!value) return;
            if (range.mode === "custom") setRange(rangeFor("custom", value, value, range.to, today));
            else setRange(rangeFor(range.mode, value, value, value, today));
          }}
          sx={{ flex: 1, bgcolor: "#fff" }}
        />
      </Stack>
      {range.mode === "custom" ? (
        <Stack direction="row" spacing={0.75} sx={{ px: 0.5, pb: 0.5 }}>
          <TextField
            type="date"
            size="small"
            label={t("issues.from")}
            value={range.from}
            InputLabelProps={{ shrink: true }}
            inputProps={{ max: today }}
            onChange={(e) => e.target.value && setRange(rangeFor("custom", e.target.value, e.target.value, range.to, today))}
            sx={{ flex: 1, bgcolor: "#fff" }}
          />
          <TextField
            type="date"
            size="small"
            label={t("issues.to")}
            value={range.to}
            InputLabelProps={{ shrink: true }}
            inputProps={{ max: today }}
            onChange={(e) => e.target.value && setRange(rangeFor("custom", range.from, range.from, e.target.value, today))}
            sx={{ flex: 1, bgcolor: "#fff" }}
          />
        </Stack>
      ) : null}
    </Box>
  );

  return (
    <OpsMobileShell maxWidth={560} showLocaleToggle={false}>
      <OpsTopBar
        title={view === "create" ? t("issues.new") : view === "detail" ? t("issues.detail") : t("issues.title")}
        backLabel={view === "list" ? undefined : t("issues.title")}
        onBack={
          view === "list"
            ? onBack
            : () => {
                setView("list");
                setDetailKey("");
                setReportDone(null);
              }
        }
        onLock={onLock}
        right={<OpsLocaleToggle />}
      />

      {view === "list" ? (
        <>
          {nav}
          <Stack direction="row" spacing={0.6}>
            <CountButton label={t("issues.total")} value={summary?.total ?? 0} selected={!statusGroup} color={OPS_MOBILE.navy} onClick={() => setStatusGroup("")} />
            <CountButton label={t("issues.open")} value={summary?.open ?? 0} selected={statusGroup === "open"} color="#b45309" onClick={() => setStatusGroup("open")} />
            <CountButton label={t("issues.review")} value={summary?.review ?? 0} selected={statusGroup === "review"} color="#1d4ed8" onClick={() => setStatusGroup("review")} />
            <CountButton label={t("issues.closed")} value={summary?.resolved ?? 0} selected={statusGroup === "resolved"} color="#0f766e" onClick={() => setStatusGroup("resolved")} />
          </Stack>
          <Stack direction="row" spacing={0.6}>
            {[
              ["all", t("issues.source.all")],
              ["employee", t("lostFound.desktopTitle")],
              ["rinse", t("issues.source.customer")],
            ].map(([value, label]) => (
              <Button
                key={value}
                onClick={() => setSource(value)}
                aria-pressed={source === value}
                sx={{
                  flex: "1 1 0",
                  minHeight: 40,
                  px: 0.75,
                  textTransform: "none",
                  fontWeight: 800,
                  fontSize: "0.78rem",
                  lineHeight: 1.15,
                  bgcolor: source === value ? alpha(OPS_MOBILE.navy, 0.1) : "#fff",
                  border: `1.5px solid ${source === value ? OPS_MOBILE.navy : alpha(OPS_MOBILE.navy, 0.08)}`,
                }}
              >
                {label}
              </Button>
            ))}
          </Stack>
          <Stack direction="row" spacing={0.6}>
            <TextField
              size="small"
              fullWidth
              placeholder={t("issues.search")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              sx={{ bgcolor: "#fff" }}
            />
            <Button
              onClick={() => setFiltersOpen((open) => !open)}
              sx={{
                flexShrink: 0,
                minHeight: 40,
                textTransform: "none",
                fontWeight: 800,
                bgcolor: "#fff",
                border: `1px solid ${alpha(OPS_MOBILE.navy, 0.12)}`,
              }}
            >
              {t("issues.filters")}
            </Button>
            <Button
              variant="contained"
              onClick={startReport}
              sx={{ flexShrink: 0, minHeight: 40, textTransform: "none", fontWeight: 800, boxShadow: "none" }}
            >
              {t("issues.new")}
            </Button>
          </Stack>
          {filtersOpen ? (
            <Stack spacing={0.75} sx={{ bgcolor: "#fff", borderRadius: "14px", p: 1 }}>
              <TextField select size="small" label={t("issues.sourceLabel")} value={source} onChange={(e) => setSource(e.target.value)}>
                <MenuItem value="all">{t("issues.source.all")}</MenuItem>
                <MenuItem value="employee">{t("issues.source.employee")}</MenuItem>
                <MenuItem value="rinse">{t("issues.source.customer")}</MenuItem>
              </TextField>
              <TextField select size="small" label={t("issues.type")} value={category} onChange={(e) => setCategory(e.target.value)}>
                {TYPE_OPTIONS.map(([value, key]) => (
                  <MenuItem key={value || "all"} value={value}>{t(key)}</MenuItem>
                ))}
              </TextField>
              <TextField size="small" label={t("issues.employee")} value={employee} onChange={(e) => setEmployee(e.target.value)} />
              <TextField select size="small" label={t("issues.sort")} value={sort} onChange={(e) => setSort(e.target.value)}>
                <MenuItem value="newest">{t("issues.sort.newest")}</MenuItem>
                <MenuItem value="oldest">{t("issues.sort.oldest")}</MenuItem>
                <MenuItem value="status">{t("issues.sort.status")}</MenuItem>
              </TextField>
            </Stack>
          ) : null}
          {error ? (
            <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => load(1)}>{t("issues.retry")}</Button>}>
              {error}
            </Alert>
          ) : null}
          {loading ? (
            <Box sx={{ py: 4, display: "grid", placeItems: "center" }}><CircularProgress size={26} /></Box>
          ) : rows.length === 0 ? (
            <Box sx={{ py: 4, textAlign: "center" }}>
              <Typography sx={{ fontWeight: 800 }}>{t("issues.empty")}</Typography>
              <Typography sx={{ color: OPS_MOBILE.muted, fontSize: "0.86rem" }}>{t("issues.emptyHint")}</Typography>
            </Box>
          ) : (
            <Stack spacing={0.75}>
              {rows.map((row) => (
                <IssueCard key={row.key} row={row} onOpen={openDetail} t={t} />
              ))}
              {rows.length < total ? (
                <Button disabled={loadingMore} onClick={() => load(page + 1)} sx={{ textTransform: "none", fontWeight: 800 }}>
                  {loadingMore ? t("issues.loading") : t("issues.more", { shown: rows.length, total })}
                </Button>
              ) : null}
            </Stack>
          )}
        </>
      ) : null}

      {view === "detail" ? (
        <Stack spacing={1}>
          {detailLoading ? (
            <Box sx={{ py: 4, display: "grid", placeItems: "center" }}><CircularProgress size={26} /></Box>
          ) : null}
          {detailError ? <Alert severity="error">{detailError}</Alert> : null}
          {current ? (
            <>
              <Box sx={{ bgcolor: "#fff", borderRadius: "16px", p: 1.25 }}>
                <Typography sx={{ fontWeight: 900, fontSize: "1.05rem" }}>
                  {detail.source === "rinse" ? t("issues.customerId", { id: current.id }) : t("issues.reportId", { id: current.id })}
                </Typography>
                <Typography sx={{ fontWeight: 750 }}>
                  {detail.row?.category_label || current.issue_category || current.report_category}
                </Typography>
                <Typography sx={{ color: OPS_MOBILE.muted, fontSize: "0.84rem" }}>
                  {current.primary_employee_name || current.employee_name || detail.row?.employee_name || "—"}
                  {" · "}
                  {formatFriendlyEtWall(current.reported_at_et || current.reported_at_display || detail.row?.reported_at)}
                </Typography>
                <Box
                  component="span"
                  sx={{
                    display: "inline-block",
                    mt: 0.6,
                    px: 0.9,
                    py: 0.2,
                    borderRadius: 99,
                    fontWeight: 800,
                    fontSize: 12,
                    color: statusColor(currentStatus),
                    bgcolor: alpha(statusColor(currentStatus), 0.12),
                  }}
                >
                  {t(`issues.status.${currentStatus}`)}
                </Box>
              </Box>
              <Box sx={{ bgcolor: "#fff", borderRadius: "16px", p: 1.25 }}>
                <DetailLine label={t("issues.place")} value={detail.row?.location || current.location_label || current.bag_id || current.manual_identifier || orderRef || "—"} />
                <DetailLine label={t("issues.order")} value={current.order_reference || current.order_display_id || current.bag_id || "—"} />
                <DetailLine label={t("issues.description")} value={current.description || current.notes || detail.row?.summary || "—"} />
                {current.customer_name_snapshot ? <DetailLine label={t("issues.customer")} value={current.customer_name_snapshot} /> : null}
              </Box>
              <Box sx={{ bgcolor: "#fff", borderRadius: "16px", p: 1.25 }}>
                <Typography sx={{ fontWeight: 800, mb: 0.6 }}>{t("issues.photoTitle")}</Typography>
                {photos.length ? (
                  <Stack direction="row" spacing={0.75} sx={{ overflowX: "auto" }}>
                    {photos.map((photo) => (
                      <Box
                        key={photo.id}
                        component="button"
                        type="button"
                        onClick={() => setZoom(photo.url)}
                        aria-label={t("issues.enlargePhoto")}
                        sx={{
                          p: 0,
                          border: 0,
                          borderRadius: "12px",
                          overflow: "hidden",
                          width: 96,
                          height: 96,
                          flexShrink: 0,
                        }}
                      >
                        <Box component="img" src={photo.url} alt="" sx={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      </Box>
                    ))}
                  </Stack>
                ) : (
                  <Typography sx={{ color: OPS_MOBILE.muted, fontSize: "0.86rem" }}>
                    {detail.source === "employee" ? t("issues.noPhoto") : t("issues.noCustomerPhoto")}
                  </Typography>
                )}
              </Box>
              <Box sx={{ bgcolor: "#fff", borderRadius: "16px", p: 1.25 }}>
                <TextField
                  fullWidth
                  multiline
                  minRows={2}
                  label={t("issues.remarks")}
                  value={remarks}
                  onChange={(e) => setRemarks(e.target.value)}
                />
                {detail.source === "employee" && allowedStatuses.includes("returned") ? (
                  <TextField
                    fullWidth
                    size="small"
                    sx={{ mt: 1 }}
                    label={t("issues.order")}
                    value={orderRef}
                    onChange={(e) => setOrderRef(e.target.value)}
                  />
                ) : null}
                {detail.source === "employee" ? (
                  <TextField
                    fullWidth
                    size="small"
                    sx={{ mt: 1 }}
                    label={t("issues.resolveReason")}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                ) : null}
                <Stack direction="row" flexWrap="wrap" useFlexGap spacing={0.6} sx={{ mt: 1 }}>
                  {allowedStatuses.includes("under_review") || allowedStatuses.includes("investigating") ? (
                    <ActionButton
                      disabled={saving}
                      label={t("issues.markReview")}
                      onClick={() => applyStatus(detail.source === "rinse" ? "investigating" : "under_review")}
                    />
                  ) : null}
                  <ActionButton disabled={saving} label={t("issues.saveRemarks")} onClick={() => applyStatus(currentStatus)} />
                  <ActionButton disabled={saving} label={t("issues.resolve")} onClick={() => applyStatus("resolved")} />
                  {detail.source === "rinse" ? (
                    <ActionButton disabled={saving} label={t("issues.close")} onClick={() => applyStatus("excluded")} />
                  ) : null}
                  {detail.source === "employee" && allowedStatuses.includes("stored") ? (
                    <ActionButton disabled={saving} label={t("issues.store")} onClick={() => applyStatus("stored")} />
                  ) : null}
                  {detail.source === "employee" && allowedStatuses.includes("returned") ? (
                    <ActionButton disabled={saving} label={t("issues.returned")} onClick={() => applyStatus("returned")} />
                  ) : null}
                  {isClosedStatus(detail.source, currentStatus) ? (
                    <ActionButton
                      disabled={saving}
                      label={t("issues.reopen")}
                      onClick={() => applyStatus(detail.source === "rinse" ? "open" : "new")}
                    />
                  ) : null}
                </Stack>
              </Box>
              <Box sx={{ bgcolor: "#fff", borderRadius: "16px", p: 1.25 }}>
                <Typography sx={{ fontWeight: 800, mb: 0.5 }}>{t("issues.history")}</Typography>
                {(detail.events || []).length === 0 ? (
                  <Typography sx={{ color: OPS_MOBILE.muted, fontSize: "0.86rem" }}>{t("issues.noHistory")}</Typography>
                ) : (
                  (detail.events || []).map((event) => (
                    <Typography key={event.id || `${event.action}-${event.created_at}`} sx={{ fontSize: "0.8rem", py: 0.35 }}>
                      {formatFriendlyEtWall(event.created_at_display || event.created_at)} · {event.event_type || event.action} · {event.actor_name || event.actor_display_name || ""}
                    </Typography>
                  ))
                )}
              </Box>
            </>
          ) : null}
        </Stack>
      ) : null}

      {view === "create" ? (
        <Stack spacing={1}>
          {reportError ? <Alert severity="error">{reportError}</Alert> : null}
          {reportDone ? (
            <Alert
              severity="success"
              action={
                <Button color="inherit" size="small" onClick={() => { setReportDone(null); setFormKey((n) => n + 1); }}>
                  {t("issues.another")}
                </Button>
              }
            >
              {t("lostFound.success")}
            </Alert>
          ) : (
            <LostFoundReportForm
              key={formKey}
              choices={reportChoices || {}}
              submitting={saving}
              onSubmit={submitReport}
            />
          )}
          {!reportChoices && !reportError ? (
            <Stack direction="row" spacing={1} alignItems="center">
              <AddAPhotoOutlinedIcon fontSize="small" />
              <Typography sx={{ fontSize: "0.82rem", color: OPS_MOBILE.muted }}>{t("issues.photoPhone")}</Typography>
            </Stack>
          ) : null}
        </Stack>
      ) : null}

      <Dialog open={Boolean(zoom)} onClose={() => setZoom("")} fullWidth maxWidth="md">
        <IconButton aria-label={t("issues.closePhoto")} onClick={() => setZoom("")} sx={{ position: "absolute", right: 8, top: 8, bgcolor: "#fff" }}>
          <CloseIcon />
        </IconButton>
        {zoom ? <Box component="img" src={zoom} alt="" sx={{ width: "100%", maxHeight: "85vh", objectFit: "contain", bgcolor: "#0f172a" }} /> : null}
      </Dialog>
    </OpsMobileShell>
  );
}

function DetailLine({ label, value }) {
  return (
    <Box sx={{ py: 0.35 }}>
      <Typography sx={{ fontSize: 11, fontWeight: 800, color: OPS_MOBILE.muted }}>{label}</Typography>
      <Typography sx={{ fontWeight: 700, fontSize: "0.92rem", whiteSpace: "pre-wrap" }}>{value}</Typography>
    </Box>
  );
}

function ActionButton({ label, onClick, disabled }) {
  return (
    <Button
      disabled={disabled}
      onClick={onClick}
      sx={{
        textTransform: "none",
        fontWeight: 800,
        minHeight: 44,
        borderRadius: "12px",
        bgcolor: alpha(OPS_MOBILE.blue, 0.08),
        color: OPS_MOBILE.navy,
      }}
    >
      {label}
    </Button>
  );
}
