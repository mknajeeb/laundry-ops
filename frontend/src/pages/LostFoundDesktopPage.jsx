import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { getLostFoundList, getLostFoundReconciliation, getRedryPockets, saveRedryPockets, updateLostFoundStatus } from "../api";
import LostFoundPhoto from "../components/lostFound/LostFoundPhoto";
import { useI18n } from "../i18n/I18nContext";
import { displayFoundEvent, displayFoundLocation } from "../utils/lostFoundLocation";
import { businessTodayYmd } from "../utils/businessTime";

const STATUSES = ["new", "under_review", "returned", "stored", "resolved"];

export default function LostFoundDesktopPage() {
  const { t } = useI18n();
  const [scope, setScope] = useState("today");
  const [date, setDate] = useState(businessTodayYmd());
  const [items, setItems] = useState([]);
  const [carried, setCarried] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState(null);
  const [category, setCategory] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [employee, setEmployee] = useState("");
  const [location, setLocation] = useState("");
  const [violation, setViolation] = useState("all");
  const [pockets, setPockets] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getLostFoundList({ scope, date });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || "Could not load Lost & Found");
      setItems(body.items || []);
      if (scope === "today") {
        const recon = await getLostFoundReconciliation(date);
        const open = (recon?.data?.items || []).filter((item) => item.carried_forward);
        setCarried(open);
      } else {
        setCarried([]);
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Could not load Lost & Found");
    } finally {
      setLoading(false);
    }
  }, [date, scope]);

  useEffect(() => {
    load();
    getRedryPockets().then((res) => {
      if (res?.data?.ok) setPockets((res.data.pockets || []).join(", "));
    }).catch(() => {});
  }, [load]);

  const save = async () => {
    if (!edit) return;
    setError("");
    try {
      const res = await updateLostFoundStatus(edit.id, {
        status: edit.status,
        order_reference: edit.order_reference,
        comment: edit.comment,
        reason: edit.reason,
      });
      if (!res?.data?.ok) throw new Error(res?.data?.error || "Could not update status");
      setEdit(null);
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Could not update status");
    }
  };

  const renderItem = (item) => (
    <Box key={`${item.id}-${item.business_date}`} sx={{ p: 1.5, border: "1px solid #e5e7eb", borderRadius: 2 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between">
        <Box>
          <Typography sx={{ fontWeight: 800 }}>
            {(item.report_category === "redry" ? t("lostFound.redryIssue") : item.report_category === "equipment" ? t("lostFound.equipmentTitle") : t("lostFound.foundTitle"))} · {displayFoundLocation(item, t)}
          </Typography>
          {item.report_category === "redry" && item.redry_bag_number ? (
            <Typography variant="body2">{t("lostFound.bagNumber")}: {item.redry_bag_number}</Typography>
          ) : null}
          {item.report_category === "redry" ? (
            <Typography variant="body2">
              {["missing_ticket", "mesh_bag", "wrong_pocket"].filter((key) => item.redry_flags?.[key]).map((key) => t(`lostFound.redry.${key === "missing_ticket" ? "missingTicket" : key === "mesh_bag" ? "meshBag" : "wrongPocket"}`)).join(" · ")}
            </Typography>
          ) : null}
          <Typography variant="body2">{item.employee_name} · {item.facility_name || ""}</Typography>
          <Typography variant="body2" color="text.secondary">{item.reported_at_display}</Typography>
          <Typography variant="body2">{t(`lostFound.status.${item.status}`)}</Typography>
          {item.order_reference ? <Typography variant="body2">{t("lostFound.orderReference")}: {item.order_reference}</Typography> : null}
          {item.status_comment ? <Typography variant="body2">{item.status_comment}</Typography> : null}
          {item.resolved_reason ? <Typography variant="body2">{item.resolved_reason}</Typography> : null}
          {item.notes ? <Typography variant="body2">{item.notes}</Typography> : null}
          <Stack spacing={0.25} sx={{ mt: 0.5 }}>
            {(item.events || []).map((event) => (
              <Typography key={event.id} variant="caption" color="text.secondary">
                {event.created_at_display} · {event.actor_name || "—"} · {displayFoundEvent(event.event_type, t)}
              </Typography>
            ))}
          </Stack>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {(item.photos || []).map((photo) => (
            <LostFoundPhoto key={photo.id} photoId={photo.id} />
          ))}
        </Stack>
      </Stack>
      <Button size="small" sx={{ mt: 1, textTransform: "none" }} onClick={() => setEdit({
        id: item.id,
        report_category: item.report_category || "orphan",
        status: item.status,
        order_reference: item.order_reference || "",
        comment: "",
        reason: item.resolved_reason || "",
      })}
      >
        {t("lostFound.update")}
      </Button>
    </Box>
  );

  return (
    <Box sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: 1100 }}>
      <Typography variant="h5" sx={{ fontWeight: 800 }}>{t("lostFound.issueReports")}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{t("lostFound.desktopTitle")}</Typography>
      <Tabs value={scope} onChange={(_, value) => setScope(value)} sx={{ mb: 1 }}>
        <Tab value="today" label={t("lostFound.today")} />
        <Tab value="history" label={t("lostFound.history")} />
      </Tabs>
      <TextField
        type="date"
        size="small"
        value={date}
        onChange={(e) => setDate(e.target.value)}
        sx={{ mb: 2 }}
      />
      <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 2 }}>
        <TextField select size="small" label={t("lostFound.category")} value={category} onChange={(e) => setCategory(e.target.value)} sx={{ minWidth: 160 }}>
          <MenuItem value="all">{t("lostFound.category")}</MenuItem>
          <MenuItem value="orphan">{t("lostFound.foundTitle")}</MenuItem>
          <MenuItem value="redry">{t("lostFound.redryIssue")}</MenuItem>
          <MenuItem value="equipment">{t("lostFound.equipmentTitle")}</MenuItem>
        </TextField>
        <TextField select size="small" label={t("lostFound.status")} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="all">{t("lostFound.status")}</MenuItem>
          {STATUSES.map((code) => <MenuItem key={code} value={code}>{t(`lostFound.status.${code}`)}</MenuItem>)}
        </TextField>
        <TextField size="small" label={t("lostFound.employee")} value={employee} onChange={(e) => setEmployee(e.target.value)} />
        <TextField size="small" label={t("lostFound.location")} value={location} onChange={(e) => setLocation(e.target.value)} />
        <TextField select size="small" label={t("lostFound.redryIssue")} value={violation} onChange={(e) => setViolation(e.target.value)} sx={{ minWidth: 180 }}>
          <MenuItem value="all">{t("lostFound.redryIssue")}</MenuItem>
          <MenuItem value="missing_ticket">{t("lostFound.redry.missingTicket")}</MenuItem>
          <MenuItem value="mesh_bag">{t("lostFound.redry.meshBag")}</MenuItem>
          <MenuItem value="wrong_pocket">{t("lostFound.redry.wrongPocket")}</MenuItem>
        </TextField>
      </Stack>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 2 }}>
        <TextField size="small" fullWidth label={t("lostFound.pockets")} value={pockets} onChange={(e) => setPockets(e.target.value)} helperText="D1, D2" />
        <Button variant="outlined" onClick={() => saveRedryPockets(pockets.split(",").map((part) => part.trim()).filter(Boolean)).then((res) => setPockets((res?.data?.pockets || []).join(", "))).catch((err) => setError(err?.response?.data?.error || err.message))} sx={{ textTransform: "none", whiteSpace: "nowrap" }}>
          {t("lostFound.savePockets")}
        </Button>
      </Stack>
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {loading ? <Typography>{t("lostFound.loading")}</Typography> : null}
      <Stack spacing={1.25}>
        {items.filter((item) => {
          if (category !== "all" && (item.report_category || "orphan") !== category) return false;
          if (statusFilter !== "all" && item.status !== statusFilter) return false;
          if (employee && !String(item.employee_name || "").toLowerCase().includes(employee.toLowerCase())) return false;
          if (location && !`${item.location_label || ""} ${item.location_number || ""}`.toLowerCase().includes(location.toLowerCase())) return false;
          if (violation !== "all" && !item.redry_flags?.[violation]) return false;
          return true;
        }).map(renderItem)}
        {!loading && !items.length ? <Typography color="text.secondary">{t("lostFound.noItems")}</Typography> : null}
        {carried.length ? (
          <>
            <Typography sx={{ fontWeight: 800, pt: 1 }}>{t("lostFound.carried")}</Typography>
            {carried.map(renderItem)}
          </>
        ) : null}
      </Stack>
      <Dialog open={!!edit} onClose={() => setEdit(null)} fullWidth maxWidth="xs">
        <DialogTitle>{t("lostFound.update")}</DialogTitle>
        <DialogContent>
          <Stack spacing={1.25} sx={{ pt: 1 }}>
            <TextField select label={t("lostFound.status")} value={edit?.status || "new"} onChange={(e) => setEdit((row) => ({ ...row, status: e.target.value }))}>
              {(edit?.report_category === "orphan" || !edit?.report_category ? STATUSES : ["new", "under_review", "resolved"]).map((code) => (
                <MenuItem key={code} value={code}>{t(`lostFound.status.${code}`)}</MenuItem>
              ))}
            </TextField>
            {edit?.status === "returned" ? (
              <TextField label={t("lostFound.orderReference")} value={edit.order_reference} onChange={(e) => setEdit((row) => ({ ...row, order_reference: e.target.value }))} />
            ) : null}
            {edit?.status === "resolved" ? (
              <TextField label={edit?.report_category === "equipment" ? t("lostFound.repairNote") : t("lostFound.reason")} value={edit.reason} onChange={(e) => setEdit((row) => ({ ...row, reason: e.target.value }))} />
            ) : null}
            <TextField label={t("lostFound.comment")} value={edit?.comment || ""} onChange={(e) => setEdit((row) => ({ ...row, comment: e.target.value }))} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEdit(null)}>{t("lostFound.back")}</Button>
          <Button variant="contained" onClick={save}>{t("lostFound.update")}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
