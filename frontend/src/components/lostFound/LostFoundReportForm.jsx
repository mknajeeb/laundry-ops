import { useEffect, useMemo, useRef, useState } from "react";
import BadgeOutlinedIcon from "@mui/icons-material/BadgeOutlined";
import CheckroomOutlinedIcon from "@mui/icons-material/CheckroomOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DryCleaningOutlinedIcon from "@mui/icons-material/DryCleaningOutlined";
import LocalLaundryServiceOutlinedIcon from "@mui/icons-material/LocalLaundryServiceOutlined";
import PhotoCameraOutlinedIcon from "@mui/icons-material/PhotoCameraOutlined";
import PhotoLibraryOutlinedIcon from "@mui/icons-material/PhotoLibraryOutlined";
import ReplayIcon from "@mui/icons-material/Replay";
import ReportProblemOutlinedIcon from "@mui/icons-material/ReportProblemOutlined";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import { Alert, Box, Button, Stack, TextField, Tooltip, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import OpsChoiceCard from "../../opsMobile/OpsChoiceCard";
import OpsStickyActionBar from "../../opsMobile/OpsStickyActionBar";
import { OPS_MOBILE } from "../../opsMobile/tokens";
import { useI18n } from "../../i18n/I18nContext";
import {
  addReportPhotos,
  displayMachineNumber,
  filterIdentifiers,
  identifierChoices,
  removeReportPhoto,
  replaceReportPhoto,
} from "../../utils/lostFoundLocation";

const CATEGORIES = [
  ["orphan", "lostFound.foundTitle", "lostFound.foundHint", CheckroomOutlinedIcon],
  ["redry", "lostFound.redryTitle", "lostFound.redryHint", DryCleaningOutlinedIcon],
  ["equipment", "lostFound.equipmentTitle", "lostFound.equipmentHint", ReportProblemOutlinedIcon],
];

const FOUND_PLACES = ["washer", "dryer", "folding_table", "floor", "cart", "other"];
const EQUIPMENT_TYPES = ["washer", "dryer", "dehumidifier", "other"];
const REDRY_FLAGS = [
  ["mesh_bag", "lostFound.redry.meshBag", LocalLaundryServiceOutlinedIcon],
  ["wrong_pocket", "lostFound.redry.wrongPocket", DryCleaningOutlinedIcon],
  ["missing_ticket", "lostFound.redry.missingTicket", BadgeOutlinedIcon],
];

function newRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `lf-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function IssueChoiceButton({ title, selected, disabled, onClick, icon: Icon }) {
  return (
    <Button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-pressed={selected}
      sx={{
        width: "100%",
        minHeight: 52,
        px: 1.1,
        py: 0.75,
        justifyContent: "flex-start",
        textAlign: "left",
        textTransform: "none",
        fontWeight: 800,
        fontSize: "0.92rem",
        lineHeight: 1.2,
        borderRadius: `${OPS_MOBILE.radius.button}px`,
        color: OPS_MOBILE.navy,
        bgcolor: selected ? alpha(OPS_MOBILE.cobalt, 0.16) : "#fff",
        border: `2px solid ${selected ? OPS_MOBILE.cobalt : alpha(OPS_MOBILE.blue, 0.32)}`,
        boxShadow: selected ? `inset 3px 0 0 ${OPS_MOBILE.cobalt}` : "none",
        "&:hover": {
          bgcolor: selected ? alpha(OPS_MOBILE.cobalt, 0.22) : alpha(OPS_MOBILE.cobalt, 0.06),
          borderColor: OPS_MOBILE.cobalt,
        },
      }}
    >
      {Icon ? (
        <Icon
          sx={{
            fontSize: 18,
            mr: 0.75,
            flexShrink: 0,
            color: selected ? OPS_MOBILE.cobalt : OPS_MOBILE.blue,
          }}
        />
      ) : null}
      <Box component="span" sx={{ minWidth: 0, whiteSpace: "normal", textAlign: "left" }}>{title}</Box>
    </Button>
  );
}

function NumberPicker({ label, options, value, onChange, optional = false }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const shown = filterIdentifiers(options, query);
  if (!options.length) {
    return (
      <TextField
        size="small"
        fullWidth
        label={label}
        value={value}
        required={!optional}
        helperText={optional ? t("lostFound.optional") : ""}
        onChange={(event) => onChange(event.target.value.slice(0, 40))}
      />
    );
  }
  return (
    <Stack spacing={0.5}>
      <Typography sx={{ fontWeight: 800, fontSize: "0.9rem", color: OPS_MOBILE.navy }}>{label}</Typography>
      {options.length > 12 ? (
        <TextField
          size="small"
          value={query}
          placeholder={t("lostFound.searchNumber")}
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, maxHeight: 112, overflowY: "auto" }}>
        {shown.map((id) => {
          const selected = value === id;
          return (
            <Button
              key={id}
              type="button"
              onClick={() => onChange(id)}
              aria-pressed={selected}
              sx={{
                minWidth: 48,
                minHeight: 44,
                px: 1.1,
                borderRadius: `${OPS_MOBILE.radius.button}px`,
                fontWeight: 800,
                textTransform: "none",
                color: selected ? "#fff" : OPS_MOBILE.navy,
                bgcolor: selected ? OPS_MOBILE.cobalt : "#fff",
                border: `2px solid ${selected ? OPS_MOBILE.cobalt : alpha(OPS_MOBILE.blue, 0.28)}`,
              }}
            >
              {displayMachineNumber(id)}
            </Button>
          );
        })}
        {!shown.length ? <Typography variant="caption">{t("lostFound.noMatches")}</Typography> : null}
      </Box>
    </Stack>
  );
}

function PhotoAction({ label, icon: Icon, onClick, tone = "default" }) {
  const color = tone === "danger" ? OPS_MOBILE.danger : tone === "accent" ? OPS_MOBILE.cobalt : OPS_MOBILE.blue;
  return (
    <Tooltip title={label}>
      <Button
        type="button"
        aria-label={label}
        onClick={onClick}
        sx={{
          flex: "1 1 0",
          minWidth: 0,
          minHeight: 48,
          px: 0.4,
          py: 0.4,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 0.15,
          textTransform: "none",
          fontWeight: 800,
          fontSize: "0.68rem",
          lineHeight: 1.15,
          whiteSpace: "normal",
          wordBreak: "break-word",
          color,
          bgcolor: alpha(color, tone === "danger" ? 0.1 : 0.08),
          border: `1px solid ${alpha(color, 0.38)}`,
          borderRadius: "10px",
          "&:hover": { bgcolor: alpha(color, 0.16) },
        }}
      >
        {Icon ? <Icon sx={{ fontSize: 18 }} /> : null}
        {label}
      </Button>
    </Tooltip>
  );
}

function PhotoManager({ photos, onChange }) {
  const { t } = useI18n();
  const cameraRef = useRef(null);
  const libraryRef = useRef(null);
  const replaceRef = useRef(null);
  const libraryReplaceRef = useRef(null);
  const replaceId = useRef("");
  const urls = useMemo(
    () => photos.map((photo) => ({ ...photo, url: URL.createObjectURL(photo.file) })),
    [photos],
  );
  useEffect(() => () => {
    urls.forEach((photo) => URL.revokeObjectURL(photo.url));
  }, [urls]);

  const captureLabel = photos.length ? t("lostFound.addMore") : t("lostFound.takePhoto");

  return (
    <Box
      sx={{
        p: 1,
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        bgcolor: "#fff",
        border: `1px solid ${OPS_MOBILE.border}`,
      }}
    >
      <Typography sx={{ fontWeight: 800, fontSize: "0.9rem", color: OPS_MOBILE.navy, mb: 0.75 }}>
        {t("lostFound.photos")} · {photos.length}
      </Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0.75 }}>
        <Button
          type="button"
          aria-label={captureLabel}
          onClick={() => cameraRef.current?.click()}
          sx={captureButtonSx}
        >
          <PhotoCameraOutlinedIcon sx={{ fontSize: 20, flexShrink: 0, color: OPS_MOBILE.cobalt }} />
          <Box component="span" sx={{ minWidth: 0, whiteSpace: "normal" }}>{captureLabel}</Box>
        </Button>
        <Button
          type="button"
          aria-label={t("lostFound.choosePhoto")}
          onClick={() => libraryRef.current?.click()}
          sx={libraryButtonSx}
        >
          <PhotoLibraryOutlinedIcon sx={{ fontSize: 20, flexShrink: 0, color: OPS_MOBILE.blue }} />
          <Box component="span" sx={{ minWidth: 0, whiteSpace: "normal" }}>{t("lostFound.choosePhoto")}</Box>
        </Button>
      </Box>
      <input ref={cameraRef} hidden type="file" accept="image/*" capture="environment" onChange={(event) => { onChange(addReportPhotos(photos, event.target.files)); event.target.value = ""; }} />
      <input ref={libraryRef} hidden type="file" accept="image/*" multiple onChange={(event) => { onChange(addReportPhotos(photos, event.target.files)); event.target.value = ""; }} />
      <input
        ref={replaceRef}
        hidden
        type="file"
        accept="image/*"
        capture="environment"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && replaceId.current) onChange(replaceReportPhoto(photos, replaceId.current, file));
          event.target.value = "";
        }}
      />
      <input
        ref={libraryReplaceRef}
        hidden
        type="file"
        accept="image/*"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && replaceId.current) onChange(replaceReportPhoto(photos, replaceId.current, file));
          event.target.value = "";
        }}
      />
      {urls.length ? (
        <Stack spacing={0.75} sx={{ mt: 0.75 }}>
          {urls.map((photo) => (
            <Box key={photo.id} sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0 }}>
              <Box
                component="img"
                src={photo.url}
                alt=""
                sx={{
                  width: 64,
                  height: 64,
                  objectFit: "cover",
                  borderRadius: "10px",
                  display: "block",
                  flexShrink: 0,
                  border: `1px solid ${OPS_MOBILE.border}`,
                }}
              />
              <Box sx={{ display: "flex", flex: 1, gap: 0.5, minWidth: 0 }}>
                <PhotoAction
                  label={t("lostFound.retake")}
                  icon={ReplayIcon}
                  tone="accent"
                  onClick={() => { replaceId.current = photo.id; replaceRef.current?.click(); }}
                />
                <PhotoAction
                  label={t("lostFound.replacePhoto")}
                  icon={SwapHorizIcon}
                  onClick={() => { replaceId.current = photo.id; libraryReplaceRef.current?.click(); }}
                />
                <PhotoAction
                  label={t("lostFound.deletePhoto")}
                  icon={DeleteOutlineIcon}
                  tone="danger"
                  onClick={() => onChange(removeReportPhoto(photos, photo.id))}
                />
              </Box>
            </Box>
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}

const captureButtonSx = {
  minHeight: 48,
  px: 1,
  py: 0.75,
  gap: 0.5,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  textTransform: "none",
  fontWeight: 800,
  fontSize: "0.9rem",
  lineHeight: 1.15,
  color: OPS_MOBILE.navy,
  borderRadius: `${OPS_MOBILE.radius.button}px`,
  border: `2px solid ${alpha(OPS_MOBILE.cobalt, 0.5)}`,
  bgcolor: alpha(OPS_MOBILE.cobalt, 0.08),
  "&:hover": { bgcolor: alpha(OPS_MOBILE.cobalt, 0.14) },
};

const libraryButtonSx = {
  minHeight: 48,
  px: 1,
  py: 0.75,
  gap: 0.5,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  textTransform: "none",
  fontWeight: 800,
  fontSize: "0.9rem",
  lineHeight: 1.15,
  color: OPS_MOBILE.navy,
  borderRadius: `${OPS_MOBILE.radius.button}px`,
  border: `2px solid ${alpha(OPS_MOBILE.blue, 0.28)}`,
  bgcolor: "#fff",
  "&:hover": { bgcolor: alpha(OPS_MOBILE.blue, 0.06) },
};

export default function LostFoundReportForm({ choices, submitting, onSubmit, initialCategory = "", initialKind = "", initialNumber = "" }) {
  const { t } = useI18n();
  const requestId = useRef(newRequestId());
  const [category, setCategory] = useState(initialCategory);
  const [kind, setKind] = useState(initialKind);
  const [number, setNumber] = useState(initialNumber);
  const [detail, setDetail] = useState("");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  const flags = {
    missing_ticket: reason === "missing_ticket",
    mesh_bag: reason === "mesh_bag",
    wrong_pocket: reason === "wrong_pocket",
  };
  const pocketOptions = (choices?.redry_pockets || []).length ? choices.redry_pockets : (choices?.dryers || []);
  const dryerRequired = category === "redry" && flags.wrong_pocket;
  const numberOptions = category === "redry" ? pocketOptions : identifierChoices(kind, choices);
  const needsNumber = dryerRequired
    || (category === "equipment" && kind && kind !== "other")
    || (category === "orphan" && ["washer", "dryer", "folding_table"].includes(kind));
  const numberOptional = (category === "orphan" && kind === "cart") || (category === "equipment" && kind === "other");

  const resetDetails = () => {
    setKind("");
    setNumber("");
    setDetail("");
    setReason("");
    setError("");
  };

  const chooseReason = (id) => {
    setReason(id);
    setError("");
    if (id !== "wrong_pocket") setNumber("");
  };

  const submit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    if (!photos.length) {
      setError(t("lostFound.photoRequired"));
      return;
    }
    if (category === "redry") {
      if (!reason) {
        setError(t("lostFound.redry.flagRequired"));
        return;
      }
      if (flags.wrong_pocket && !String(number || "").trim()) {
        setError(t("lostFound.redry.pocketRequired"));
        return;
      }
    } else if (category === "equipment") {
      if (!kind) {
        setError(t("lostFound.error.invalid_equipment"));
        return;
      }
      if (kind === "other" && String(detail || "").trim().length < 2) {
        setError(t("lostFound.error.equipment_name_required"));
        return;
      }
      if (kind !== "other" && !String(number || "").trim()) {
        setError(t("lostFound.error.identifier_required"));
        return;
      }
    } else if (!kind) {
      setError(t("lostFound.error.invalid_location"));
      return;
    } else if (needsNumber && !String(number || "").trim()) {
      setError(t("lostFound.error.location_number_required"));
      return;
    } else if (kind === "other" && String(detail || "").trim().length < 2) {
      setError(t("lostFound.error.location_detail_required"));
      return;
    }
    setError("");
    await onSubmit({
      client_request_id: requestId.current,
      report_category: category === "orphan" ? "orphan" : category,
      location_kind: category === "redry" ? "dryer" : kind,
      location_number: dryerRequired || category !== "redry" ? number : "",
      location_detail: category === "redry" ? "" : detail,
      notes,
      files: photos.map((photo) => photo.file),
      redry_missing_ticket: flags.missing_ticket,
      redry_mesh_bag: flags.mesh_bag,
      redry_wrong_pocket: flags.wrong_pocket,
    });
  };

  const places = category === "equipment" ? EQUIPMENT_TYPES : FOUND_PLACES;

  return (
    <Stack component="form" spacing={1} onSubmit={submit} sx={{ flex: "1 1 auto" }}>
      {error ? <Alert severity="warning" sx={{ py: 0.25 }}>{error}</Alert> : null}
      {category ? (
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ minHeight: 36 }}>
          <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy, fontSize: "1.05rem", lineHeight: 1.2 }}>
            {t(CATEGORIES.find(([id]) => id === category)?.[1] || "")}
          </Typography>
          <Button
            type="button"
            disabled={submitting}
            onClick={() => { setCategory(""); resetDetails(); }}
            sx={{ minHeight: 36, px: 1, py: 0.25, textTransform: "none", fontWeight: 800, color: OPS_MOBILE.blue }}
          >
            {t("lostFound.changeCategory")}
          </Button>
        </Stack>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr 1fr" },
            gap: 1,
          }}
        >
          {CATEGORIES.map(([id, title, hint, Icon]) => (
            <OpsChoiceCard
              key={id}
              title={t(title)}
              subtitle={t(hint)}
              icon={Icon}
              selected={false}
              compact
              disabled={submitting}
              sx={{ minHeight: 84 }}
              onClick={() => {
                setCategory(id);
                resetDetails();
                if (id === "redry") setKind("dryer");
              }}
            />
          ))}
        </Box>
      )}

      {category === "redry" ? (
        <Stack spacing={0.75}>
          <Typography sx={{ fontWeight: 800, fontSize: "0.9rem", color: OPS_MOBILE.navy }}>{t("lostFound.redry.oneReason")}</Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0.75 }}>
            {REDRY_FLAGS.map(([id, key, Icon]) => (
              <IssueChoiceButton
                key={id}
                title={t(key)}
                icon={Icon}
                selected={reason === id}
                disabled={submitting}
                onClick={() => chooseReason(id)}
              />
            ))}
          </Box>
        </Stack>
      ) : null}

      {category && category !== "redry" ? (
        <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0.75 }}>
          {places.map((id) => (
            <IssueChoiceButton
              key={id}
              title={t(`lostFound.location.${id}`)}
              selected={kind === id}
              disabled={submitting}
              onClick={() => { setKind(id); setNumber(""); setDetail(""); setError(""); }}
            />
          ))}
        </Box>
      ) : null}

      {category && (needsNumber || numberOptional) ? (
        <NumberPicker
          label={category === "redry" ? t("lostFound.redry.pocket") : t(`lostFound.number.${kind || "cart"}`)}
          options={numberOptional ? (kind === "other" ? numberOptions : []) : numberOptions}
          value={number}
          optional={numberOptional}
          onChange={setNumber}
        />
      ) : null}

      {category === "orphan" && kind === "other" ? (
        <TextField size="small" required label={t("lostFound.otherDetail")} value={detail} onChange={(event) => setDetail(event.target.value)} />
      ) : null}
      {category === "equipment" && kind === "other" ? (
        <TextField size="small" required label={t("lostFound.equipmentName")} value={detail} onChange={(event) => setDetail(event.target.value)} />
      ) : null}

      {category ? (
        <>
          <PhotoManager photos={photos} onChange={setPhotos} />
          <TextField
            size="small"
            label={t("lostFound.notes")}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            helperText={t("lostFound.optional")}
            slotProps={{ formHelperText: { sx: { mt: 0.25, mx: 0 } } }}
          />
          <Box sx={{ flex: "1 1 0px", minHeight: 0 }} />
          <OpsStickyActionBar sx={{ pt: 0.75, pb: 0 }}>
            <Button
              type="submit"
              fullWidth
              disabled={submitting}
              sx={{
                minHeight: 52,
                fontWeight: 800,
                fontSize: "1.05rem",
                textTransform: "none",
                color: "#fff",
                bgcolor: OPS_MOBILE.navy,
                borderRadius: `${OPS_MOBILE.radius.button}px`,
                "&:hover": { bgcolor: OPS_MOBILE.blue },
              }}
            >
              {submitting ? t("lostFound.submitting") : t("lostFound.submit")}
            </Button>
          </OpsStickyActionBar>
        </>
      ) : null}
    </Stack>
  );
}
