import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  Drawer,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { Link as RouterLink } from "react-router-dom";
import { getLostFoundList, getLostFoundPhoto, getRedryPockets, saveRedryPockets, updateLostFoundStatus } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { displayFoundEvent, displayFoundLocation, displayMachineNumber } from "../utils/lostFoundLocation";
import { businessTodayYmd } from "../utils/businessTime";

const PAGE_SIZE = 25;
const FOUND_STATUSES = ["new", "under_review", "returned", "stored", "resolved"];
const OTHER_STATUSES = ["new", "under_review", "resolved"];

function categoryLabel(item, t) {
  if (item?.report_category === "redry") return t("lostFound.redryIssue");
  if (item?.report_category === "equipment") return t("lostFound.equipmentTitle");
  return t("lostFound.foundTitle");
}

function problemLabel(item, t) {
  if (item?.report_category === "redry") {
    return ["mesh_bag", "missing_ticket", "wrong_pocket"]
      .filter((key) => item.redry_flags?.[key])
      .map((key) => t(`lostFound.redry.${key === "missing_ticket" ? "missingTicket" : key === "mesh_bag" ? "meshBag" : "wrongPocket"}`))
      .join(" · ");
  }
  const place = displayFoundLocation(item, t);
  const number = displayMachineNumber(item?.location_number);
  return number && place && !place.endsWith(number) ? `${place}` : place;
}

function statusesFor(item) {
  return item?.report_category === "orphan" || !item?.report_category ? FOUND_STATUSES : OTHER_STATUSES;
}

function PhotoViewer({ photos, index, onClose, onIndex }) {
  const { t } = useI18n();
  const photo = photos[index];
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setUrl("");
    setFailed(false);
    if (!photo?.id) return undefined;
    getLostFoundPhoto(photo.id)
      .then((res) => {
        if (cancelled) return;
        if (res?.status >= 400 || !(res?.data instanceof Blob) || res.data.size < 8) {
          setFailed(true);
          return;
        }
        objectUrl = URL.createObjectURL(res.data);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [photo?.id]);

  const download = async () => {
    const res = await getLostFoundPhoto(photo.id, { download: true });
    if (res?.status >= 400 || !(res?.data instanceof Blob) || res.data.size < 8) {
      setFailed(true);
      return;
    }
    const objectUrl = URL.createObjectURL(res.data);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `issue-photo-${photo.id}.jpg`;
    link.click();
    URL.revokeObjectURL(objectUrl);
  };

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 1, py: 0.5 }}>
        <IconButton aria-label={t("lostFound.previous")} disabled={index <= 0} onClick={() => onIndex(index - 1)}>
          <ChevronLeftIcon />
        </IconButton>
        <Typography sx={{ fontWeight: 700 }}>{index + 1} / {photos.length}</Typography>
        <IconButton aria-label={t("lostFound.next")} disabled={index >= photos.length - 1} onClick={() => onIndex(index + 1)}>
          <ChevronRightIcon />
        </IconButton>
      </Stack>
      <Box sx={{ minHeight: 280, display: "flex", alignItems: "center", justifyContent: "center", bgcolor: "#0f172a" }}>
        {failed ? <Typography sx={{ color: "#fff", p: 2 }}>{t("lostFound.photoUnavailable")}</Typography> : null}
        {url ? <Box component="img" src={url} alt="" sx={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain" }} /> : null}
      </Box>
      <Stack direction="row" justifyContent="flex-end" spacing={1} sx={{ p: 1.5 }}>
        <Button onClick={onClose}>{t("lostFound.back")}</Button>
        <Button variant="contained" onClick={download} disabled={!photo}>{t("lostFound.download")}</Button>
      </Stack>
    </Dialog>
  );
}

export default function LostFoundDesktopPage() {
  const { t } = useI18n();
  const today = businessTodayYmd();
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(today);
  const [employeeId, setEmployeeId] = useState("");
  const [employees, setEmployees] = useState([]);
  const [category, setCategory] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [location, setLocation] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [photoIndex, setPhotoIndex] = useState(-1);
  const [pockets, setPockets] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getLostFoundList({
        date_from: dateFrom,
        date_to: dateTo,
        employee_id: employeeId || undefined,
        category,
        status: statusFilter,
        location,
        page,
        page_size: PAGE_SIZE,
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not load Issue Reports");
      setItems(body.items || []);
      setTotal(Number(body.total || 0));
      setEmployees(body.employees || []);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Could not load Issue Reports");
    } finally {
      setLoading(false);
    }
  }, [category, dateFrom, dateTo, employeeId, location, page, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    getRedryPockets()
      .then((res) => {
        if (res?.data?.ok) setPockets((res.data.pockets || []).join(", "));
      })
      .catch(() => {});
  }, []);

  const clearFilters = () => {
    const day = businessTodayYmd();
    setDateFrom(day);
    setDateTo(day);
    setEmployeeId("");
    setCategory("all");
    setStatusFilter("all");
    setLocation("");
    setPage(1);
  };

  const save = async () => {
    if (!selected) return;
    setError("");
    try {
      const res = await updateLostFoundStatus(selected.id, {
        status: selected.status,
        order_reference: selected.order_reference,
        comment: selected.comment,
        reason: selected.reason,
      });
      if (!res?.data?.ok) throw new Error(res?.data?.error || "Could not update status");
      setSelected(res.data.item || null);
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Could not update status");
    }
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: 1200 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Typography variant="h5" sx={{ fontWeight: 800 }}>{t("lostFound.issueReports")}</Typography>
        <Button component={RouterLink} to="/report-issue" variant="contained" sx={{ textTransform: "none" }}>
          {t("lostFound.report")}
        </Button>
      </Stack>
      <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} sx={{ my: 1.5 }}>
        <TextField type="date" size="small" label={t("lostFound.dateFrom")} value={dateFrom} onChange={(e) => { setPage(1); setDateFrom(e.target.value); }} InputLabelProps={{ shrink: true }} />
        <TextField type="date" size="small" label={t("lostFound.dateTo")} value={dateTo} onChange={(e) => { setPage(1); setDateTo(e.target.value); }} InputLabelProps={{ shrink: true }} />
        <TextField select size="small" label={t("lostFound.employee")} value={employeeId} onChange={(e) => { setPage(1); setEmployeeId(e.target.value); }} sx={{ minWidth: 180 }}>
          <MenuItem value="">{t("lostFound.allEmployees")}</MenuItem>
          {employees.map((person) => <MenuItem key={person.id} value={String(person.id)}>{person.name}</MenuItem>)}
        </TextField>
        <TextField select size="small" label={t("lostFound.category")} value={category} onChange={(e) => { setPage(1); setCategory(e.target.value); }} sx={{ minWidth: 170 }}>
          <MenuItem value="all">{t("lostFound.all")}</MenuItem>
          <MenuItem value="orphan">{t("lostFound.foundTitle")}</MenuItem>
          <MenuItem value="redry">{t("lostFound.redryIssue")}</MenuItem>
          <MenuItem value="equipment">{t("lostFound.equipmentTitle")}</MenuItem>
        </TextField>
        <TextField select size="small" label={t("lostFound.status")} value={statusFilter} onChange={(e) => { setPage(1); setStatusFilter(e.target.value); }} sx={{ minWidth: 150 }}>
          <MenuItem value="all">{t("lostFound.all")}</MenuItem>
          {FOUND_STATUSES.map((code) => <MenuItem key={code} value={code}>{t(`lostFound.status.${code}`)}</MenuItem>)}
        </TextField>
        <TextField size="small" label={t("lostFound.location")} value={location} onChange={(e) => { setPage(1); setLocation(e.target.value); }} />
        <Button onClick={clearFilters} sx={{ textTransform: "none" }}>{t("lostFound.clearFilters")}</Button>
      </Stack>
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t("lostFound.when")}</TableCell>
            <TableCell>{t("lostFound.category")}</TableCell>
            <TableCell>{t("lostFound.problem")}</TableCell>
            <TableCell>{t("lostFound.employee")}</TableCell>
            <TableCell>{t("lostFound.status")}</TableCell>
            <TableCell>{t("lostFound.photosCount")}</TableCell>
            <TableCell>{t("lostFound.actions")}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id} hover onClick={() => setSelected({ ...item, comment: "", reason: item.resolved_reason || "", order_reference: item.order_reference || "" })} sx={{ cursor: "pointer" }}>
              <TableCell sx={{ whiteSpace: "nowrap" }}>{item.reported_at_display}</TableCell>
              <TableCell>{categoryLabel(item, t)}</TableCell>
              <TableCell>{problemLabel(item, t)}</TableCell>
              <TableCell>{item.employee_name}</TableCell>
              <TableCell>{t(`lostFound.status.${item.status}`)}</TableCell>
              <TableCell>{(item.photos || []).length}</TableCell>
              <TableCell>
                <Button size="small" sx={{ textTransform: "none" }} onClick={(event) => { event.stopPropagation(); setSelected({ ...item, comment: "", reason: item.resolved_reason || "", order_reference: item.order_reference || "" }); }}>
                  {t("lostFound.view")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {!loading && !items.length ? (
            <TableRow>
              <TableCell colSpan={7}>{t("lostFound.noItems")}</TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
        <Button disabled={page <= 1} onClick={() => setPage((n) => n - 1)} sx={{ textTransform: "none" }}>{t("lostFound.previous")}</Button>
        <Typography variant="body2">{t("lostFound.page")} {page} / {pages}</Typography>
        <Button disabled={page >= pages} onClick={() => setPage((n) => n + 1)} sx={{ textTransform: "none" }}>{t("lostFound.next")}</Button>
        {loading ? <Typography variant="body2">{t("lostFound.loading")}</Typography> : null}
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2, maxWidth: 640 }}>
        <TextField size="small" fullWidth label={t("lostFound.pockets")} value={pockets} onChange={(e) => setPockets(e.target.value)} />
        <Button variant="outlined" onClick={() => saveRedryPockets(pockets.split(",").map((part) => part.trim()).filter(Boolean)).then((res) => setPockets((res?.data?.pockets || []).join(", "))).catch((err) => setError(err?.response?.data?.error || err.message))} sx={{ textTransform: "none", whiteSpace: "nowrap" }}>
          {t("lostFound.savePockets")}
        </Button>
      </Stack>

      <Drawer anchor="right" open={!!selected} onClose={() => setSelected(null)} PaperProps={{ sx: { width: { xs: "100%", sm: 420 }, p: 2 } }}>
        {selected ? (
          <Stack spacing={1.25}>
            <Typography variant="h6" sx={{ fontWeight: 800 }}>{t("lostFound.details")}</Typography>
            <Typography sx={{ fontWeight: 700 }}>{categoryLabel(selected, t)}</Typography>
            <Typography>{problemLabel(selected, t)}</Typography>
            <Typography variant="body2">{selected.employee_name}</Typography>
            {selected.employee_code ? (
              <Typography variant="caption" color="text.secondary">{selected.employee_code}</Typography>
            ) : null}
            <Typography variant="body2">{selected.reported_at_display}</Typography>
            {selected.notes ? <Typography variant="body2">{selected.notes}</Typography> : null}
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {(selected.photos || []).map((photo, index) => (
                <Button key={photo.id} variant="outlined" onClick={() => setPhotoIndex(index)} sx={{ minHeight: 44, textTransform: "none" }}>
                  {t("lostFound.view")} {index + 1}
                </Button>
              ))}
            </Stack>
            <TextField select label={t("lostFound.status")} value={selected.status || "new"} onChange={(e) => setSelected((row) => ({ ...row, status: e.target.value }))}>
              {statusesFor(selected).map((code) => <MenuItem key={code} value={code}>{t(`lostFound.status.${code}`)}</MenuItem>)}
            </TextField>
            {selected.status === "returned" ? (
              <TextField label={t("lostFound.orderReference")} value={selected.order_reference || ""} onChange={(e) => setSelected((row) => ({ ...row, order_reference: e.target.value }))} />
            ) : null}
            {selected.status === "resolved" ? (
              <TextField label={selected.report_category === "equipment" ? t("lostFound.repairNote") : t("lostFound.reason")} value={selected.reason || ""} onChange={(e) => setSelected((row) => ({ ...row, reason: e.target.value }))} />
            ) : null}
            <TextField label={t("lostFound.comment")} value={selected.comment || ""} onChange={(e) => setSelected((row) => ({ ...row, comment: e.target.value }))} />
            <Button variant="contained" onClick={save} sx={{ textTransform: "none" }}>{t("lostFound.update")}</Button>
            <Typography sx={{ fontWeight: 800, pt: 1 }}>{t("lostFound.history")}</Typography>
            {(selected.events || []).map((event) => (
              <Typography key={event.id} variant="body2" color="text.secondary">
                {event.created_at_display} · {event.actor_name || "—"} · {displayFoundEvent(event.event_type, t)}
              </Typography>
            ))}
          </Stack>
        ) : null}
      </Drawer>
      {photoIndex >= 0 && selected?.photos?.length ? (
        <PhotoViewer
          photos={selected.photos}
          index={photoIndex}
          onClose={() => setPhotoIndex(-1)}
          onIndex={setPhotoIndex}
        />
      ) : null}
    </Box>
  );
}
