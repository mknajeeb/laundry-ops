import { useEffect, useMemo, useRef, useState } from "react";
import CheckroomOutlinedIcon from "@mui/icons-material/CheckroomOutlined";
import DryCleaningOutlinedIcon from "@mui/icons-material/DryCleaningOutlined";
import ReportProblemOutlinedIcon from "@mui/icons-material/ReportProblemOutlined";
import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { alpha } from "@mui/material/styles";
import OpsChoiceCard from "../../opsMobile/OpsChoiceCard";
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
  ["mesh_bag", "lostFound.redry.meshBag"],
  ["wrong_pocket", "lostFound.redry.wrongPocket"],
  ["missing_ticket", "lostFound.redry.missingTicket"],
];

function newRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `lf-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
    <Stack spacing={0.75}>
      <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>{label}</Typography>
      {options.length > 12 ? (
        <TextField
          size="small"
          value={query}
          placeholder={t("lostFound.searchNumber")}
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, maxHeight: 180, overflowY: "auto" }}>
        {shown.map((id) => {
          const selected = value === id;
          return (
            <Button
              key={id}
              type="button"
              onClick={() => onChange(id)}
              aria-pressed={selected}
              sx={{
                minWidth: 52,
                minHeight: 48,
                px: 1.25,
                borderRadius: `${OPS_MOBILE.radius.button}px`,
                fontWeight: 800,
                textTransform: "none",
                color: selected ? "#fff" : OPS_MOBILE.navy,
                bgcolor: selected ? OPS_MOBILE.cobalt : "#fff",
                border: `2px solid ${selected ? OPS_MOBILE.cobalt : OPS_MOBILE.border}`,
                boxShadow: `0 8px 18px -16px ${alpha(OPS_MOBILE.navy, 0.7)}`,
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

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        bgcolor: "#fff",
        border: `1px solid ${OPS_MOBILE.border}`,
      }}
    >
      <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy, mb: 1 }}>
        {t("lostFound.photos")} · {photos.length}
      </Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={0.75}>
        <Button type="button" onClick={() => cameraRef.current?.click()} sx={photoButtonSx}>
          {photos.length ? t("lostFound.addMore") : t("lostFound.takePhoto")}
        </Button>
        <Button type="button" onClick={() => libraryRef.current?.click()} sx={photoButtonSx}>
          {t("lostFound.choosePhoto")}
        </Button>
      </Stack>
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
        <Stack direction="row" spacing={1} sx={{ overflowX: "auto", mt: 1.25 }}>
          {urls.map((photo) => (
            <Box key={photo.id} sx={{ width: 112, flexShrink: 0 }}>
              <Box component="img" src={photo.url} alt="" sx={{ width: 112, height: 112, objectFit: "cover", borderRadius: `${OPS_MOBILE.radius.button}px`, display: "block" }} />
              <Stack direction="row" spacing={0.25} sx={{ mt: 0.25 }}>
                <Button type="button" size="small" sx={tinySx} onClick={() => { replaceId.current = photo.id; replaceRef.current?.click(); }}>
                  {t("lostFound.retake")}
                </Button>
                <Button type="button" size="small" sx={tinySx} onClick={() => { replaceId.current = photo.id; libraryReplaceRef.current?.click(); }}>
                  {t("lostFound.replacePhoto")}
                </Button>
                <Button type="button" size="small" sx={tinySx} onClick={() => onChange(removeReportPhoto(photos, photo.id))}>
                  {t("lostFound.deletePhoto")}
                </Button>
              </Stack>
            </Box>
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}

const photoButtonSx = {
  flex: 1,
  minHeight: 52,
  textTransform: "none",
  fontWeight: 800,
  color: OPS_MOBILE.navy,
  borderRadius: `${OPS_MOBILE.radius.button}px`,
  border: `2px solid ${OPS_MOBILE.border}`,
  bgcolor: "#fff",
};

const tinySx = { minWidth: 0, minHeight: 40, px: 0.5, textTransform: "none", fontWeight: 700, color: OPS_MOBILE.blue };

export default function LostFoundReportForm({ choices, submitting, onSubmit }) {
  const { t } = useI18n();
  const requestId = useRef(newRequestId());
  const [category, setCategory] = useState("");
  const [kind, setKind] = useState("");
  const [number, setNumber] = useState("");
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
    <Stack component="form" spacing={1.5} onSubmit={submit}>
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {category ? (
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography sx={{ fontWeight: 900, color: OPS_MOBILE.navy, fontSize: "1.15rem" }}>
            {t(CATEGORIES.find(([id]) => id === category)?.[1] || "")}
          </Typography>
          <Button
            type="button"
            disabled={submitting}
            onClick={() => { setCategory(""); resetDetails(); }}
            sx={{ textTransform: "none", fontWeight: 800, color: OPS_MOBILE.blue }}
          >
            {t("lostFound.changeCategory")}
          </Button>
        </Stack>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "1fr 1fr 1fr" },
            gap: 1.25,
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
        <Stack spacing={1}>
          <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>{t("lostFound.redry.oneReason")}</Typography>
          {REDRY_FLAGS.map(([id, key]) => (
            <OpsChoiceCard
              key={id}
              title={t(key)}
              selected={reason === id}
              compact
              disabled={submitting}
              onClick={() => chooseReason(id)}
              sx={{ minHeight: 72 }}
            />
          ))}
        </Stack>
      ) : null}

      {category && category !== "redry" ? (
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", sm: "1fr 1fr 1fr" }, gap: 1 }}>
          {places.map((id) => (
            <OpsChoiceCard
              key={id}
              title={t(`lostFound.location.${id}`)}
              selected={kind === id}
              compact
              disabled={submitting}
              onClick={() => { setKind(id); setNumber(""); setDetail(""); setError(""); }}
              sx={{ minHeight: 72, px: 1.5, py: 1.25 }}
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
          />
          <Button
            type="submit"
            disabled={submitting}
            sx={{
              position: "sticky",
              bottom: 0,
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
        </>
      ) : null}
    </Stack>
  );
}
