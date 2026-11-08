import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  attendancePinCleaningTasksCompleteUntimed,
  pinLostFoundAccount,
  pinLostFoundBoxPhoto,
  pinLostFoundLocations,
  pinLostFoundReconciliation,
  pinLostFoundReport,
} from "../api";
import LostFoundPhoto from "../components/lostFound/LostFoundPhoto";
import LostFoundReportForm from "../components/lostFound/LostFoundReportForm";
import { useI18n } from "../i18n/I18nContext";
import { OpsMobileShell, OpsTopBar } from "../opsMobile";
import { clearPinHubSession, loadPinHubSession, pinHubMenuPath } from "../utils/pinHubSession";
import { displayFoundEvent, displayFoundLocation } from "../utils/lostFoundLocation";

const STATUSES = ["new", "under_review", "returned", "stored", "resolved"];

function slugOf(raw) {
  try {
    return decodeURIComponent(String(raw || "")).toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 64);
  } catch {
    return "";
  }
}

function flagLine(item, t) {
  const flags = item.redry_flags || {};
  return ["missing_ticket", "mesh_bag", "wrong_pocket"]
    .filter((key) => flags[key])
    .map((key) => t(`lostFound.redry.${key === "missing_ticket" ? "missingTicket" : key === "mesh_bag" ? "meshBag" : "wrongPocket"}`))
    .join(" · ");
}

function ItemCard({ item, hub, busy, onSave }) {
  const { t } = useI18n();
  const statuses = item.report_category === "orphan" || !item.report_category ? STATUSES : ["new", "under_review", "resolved"];
  const [status, setStatus] = useState(item.status || "new");
  const [orderReference, setOrderReference] = useState(item.order_reference || "");
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState(item.resolved_reason || "");
  const changed = status !== item.status;
  return (
    <Stack spacing={1} sx={{ p: 1.25, border: "1px solid #dbe3ef", borderRadius: 2, bgcolor: "#fff" }}>
      <Typography sx={{ fontWeight: 900 }}>{displayFoundLocation(item, t)}</Typography>
      <Typography variant="body2" color="text.secondary">
        {item.employee_name} · {item.reported_at_display}
        {item.carried_forward ? ` · ${t("lostFound.carried")}` : ""}
      </Typography>
      {flagLine(item, t) ? <Typography variant="body2">{flagLine(item, t)}</Typography> : null}
      {item.notes ? <Typography variant="body2">{item.notes}</Typography> : null}
      <Stack direction="row" spacing={1} sx={{ overflowX: "auto" }}>
        {(item.photos || []).filter((p) => p.photo_role !== "box").map((photo) => (
          <LostFoundPhoto key={photo.id} photoId={photo.id} hub={hub} />
        ))}
      </Stack>
      {(item.events || []).length ? (
        <Stack spacing={0.25}>
          {(item.events || []).map((event) => (
            <Typography key={event.id} variant="caption" color="text.secondary">
              {event.created_at_display} · {event.actor_name || t("lostFound.employee")} · {displayFoundEvent(event.event_type, t)}
              {event.payload?.comment ? ` — ${event.payload.comment}` : ""}
            </Typography>
          ))}
        </Stack>
      ) : null}
      <TextField select size="small" label={t("lostFound.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
        {statuses.map((code) => (
          <MenuItem key={code} value={code}>{t(`lostFound.status.${code}`)}</MenuItem>
        ))}
      </TextField>
      {status === "returned" ? (
        <TextField size="small" label={t("lostFound.orderReference")} value={orderReference} onChange={(e) => setOrderReference(e.target.value)} />
      ) : null}
      {status === "resolved" ? (
        <TextField size="small" label={item.report_category === "equipment" ? t("lostFound.repairNote") : t("lostFound.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
      ) : null}
      <TextField size="small" label={t("lostFound.comment")} value={comment} onChange={(e) => setComment(e.target.value)} />
      <Stack direction="row" spacing={1}>
        <Button disabled={busy} onClick={() => onSave(item, { action: "confirm", comment })} sx={{ textTransform: "none", fontWeight: 800 }}>
          {t("lostFound.confirm")}
        </Button>
        <Button disabled={busy} onClick={() => onSave(item, { action: "escalate", comment })} sx={{ textTransform: "none", fontWeight: 800 }}>
          {t("lostFound.escalate")}
        </Button>
        <Button
          disabled={busy || !changed}
          variant="contained"
          onClick={() => onSave(item, { action: "update", status, order_reference: orderReference, comment, reason })}
          sx={{ textTransform: "none", fontWeight: 800 }}
        >
          {t("lostFound.update")}
        </Button>
      </Stack>
    </Stack>
  );
}

export default function LostFoundReconcilePinPage() {
  const { orgSlug } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const slug = slugOf(orgSlug);
  const hub = useMemo(() => loadPinHubSession(), []);
  const [data, setData] = useState(null);
  const [choices, setChoices] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const responsibilityId = params.get("responsibility_id");

  const load = useCallback(async () => {
    if (!hub?.token || !slug) return;
    const res = await pinLostFoundReconciliation(slug, hub.pin, { hubToken: hub.token });
    const body = res?.data || {};
    if (!body.ok) throw new Error(body.error || t("lostFound.saveFailed"));
    setData(body);
  }, [hub, slug, t]);

  useEffect(() => {
    load().catch((err) => setError(err?.response?.data?.error || err.message));
    if (!hub?.token) return undefined;
    pinLostFoundLocations(slug, hub.pin, { hubToken: hub.token })
      .then((res) => {
        if (res?.data?.ok) setChoices(res.data);
      })
      .catch(() => {});
    return undefined;
  }, [hub, load, slug]);

  const lock = () => {
    clearPinHubSession();
    navigate(`/pin/${encodeURIComponent(slug)}`, { replace: true });
  };

  const save = async (item, payload) => {
    setBusy(true);
    setError("");
    try {
      const res = await pinLostFoundAccount(slug, hub.pin, {
        hubToken: hub.token,
        item_id: item.id,
        ...payload,
      });
      if (!res?.data?.ok) throw new Error(res?.data?.error || t("lostFound.saveFailed"));
      setData(res.data);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t("lostFound.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const uploadBox = async (file) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const res = await pinLostFoundBoxPhoto(slug, hub.pin, { hubToken: hub.token, file });
      if (!res?.data?.ok) throw new Error(res?.data?.error || t("lostFound.saveFailed"));
      setData(res.data);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t("lostFound.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const reportAnother = async (payload) => {
    setBusy(true);
    setError("");
    try {
      const res = await pinLostFoundReport(slug, hub.pin, { hubToken: hub.token, ...payload });
      if (!res?.data?.ok) throw new Error(res?.data?.error || t("lostFound.saveFailed"));
      setShowReport(false);
      await load();
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t("lostFound.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    if (!responsibilityId) {
      setError(t("lostFound.needAssignment"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await attendancePinCleaningTasksCompleteUntimed(slug, hub.pin, {
        hubToken: hub.token,
        responsibility_id: Number(responsibilityId),
      });
      const body = res?.data || {};
      if (!body.ok) throw new Error(body.error || t("lostFound.saveFailed"));
      navigate(pinHubMenuPath(slug), { replace: true });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t("lostFound.saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const stored = (data?.items || []).some((item) => item.status === "stored");

  return (
    <OpsMobileShell>
      <OpsTopBar
        title={t("lostFound.reconcileTitle")}
        onBack={() => navigate(pinHubMenuPath(slug))}
        onLock={lock}
        identity={hub?.employee_first_name || hub?.employee_name || ""}
      />
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {(data?.blockers || []).map((blocker) => (
        <Alert key={`${blocker.code}-${blocker.item_id || "day"}`} severity="warning" sx={{ mb: 1 }}>
          {blocker.message}
        </Alert>
      ))}
      <Stack spacing={1.25}>
        <Typography sx={{ fontWeight: 800 }}>
          {t("lostFound.orphan")} {data?.counts?.orphan ?? (data?.items || []).length}
          {" · "}
          {t("lostFound.redryIssue")} {data?.counts?.redry ?? (data?.redry_items || []).length}
          {" · "}
          {t("lostFound.equipmentTitle")} {data?.counts?.equipment ?? (data?.equipment_items || []).length}
        </Typography>
        {(data?.items || []).map((item) => (
          <ItemCard key={item.id} item={item} hub={hub} busy={busy} onSave={save} />
        ))}
        {(data?.redry_items || []).length ? (
          <Typography sx={{ fontWeight: 800, pt: 1 }}>{t("lostFound.redry.section")}</Typography>
        ) : null}
        {(data?.redry_items || []).map((item) => (
          <ItemCard key={`redry-${item.id}`} item={item} hub={hub} busy={busy} onSave={save} />
        ))}
        {(data?.equipment_items || []).length ? (
          <Typography sx={{ fontWeight: 800, pt: 1 }}>{t("lostFound.equipmentSection")}</Typography>
        ) : null}
        {(data?.equipment_items || []).map((item) => (
          <ItemCard key={`equipment-${item.id}`} item={item} hub={hub} busy={busy} onSave={save} />
        ))}
        {!data?.items?.length ? <Typography color="text.secondary">{t("lostFound.noItems")}</Typography> : null}
        {stored ? (
          <Stack spacing={1}>
            <Typography sx={{ fontWeight: 800 }}>{t("lostFound.boxPhoto")}</Typography>
            {data?.box_photo ? <LostFoundPhoto photoId={data.box_photo.id} hub={hub} /> : null}
            <Button variant="outlined" component="label" disabled={busy} sx={{ textTransform: "none", fontWeight: 800 }}>
              {t("lostFound.takePhoto")}
              <input
                hidden
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(e) => uploadBox(e.target.files?.[0])}
              />
            </Button>
          </Stack>
        ) : null}
        {showReport ? (
          <LostFoundReportForm choices={choices} submitting={busy} onSubmit={reportAnother} />
        ) : (
          <Button onClick={() => setShowReport(true)} sx={{ textTransform: "none", fontWeight: 800 }}>
            {t("lostFound.reportAnother")}
          </Button>
        )}
        {data?.snapshot ? (
          <Typography variant="caption" color="text.secondary">
            {t("lostFound.snapshot")} {data.snapshot.completed_at_display} · {data.snapshot.completed_by_name}
          </Typography>
        ) : null}
        <Button variant="contained" color="success" disabled={busy} onClick={finish} sx={{ fontWeight: 900, textTransform: "none", py: 1.25 }}>
          {t("lostFound.finish")}
        </Button>
      </Stack>
    </OpsMobileShell>
  );
}
