import { useEffect, useMemo, useRef, useState } from "react";
import CheckroomOutlinedIcon from "@mui/icons-material/CheckroomOutlined";
import DryCleaningOutlinedIcon from "@mui/icons-material/DryCleaningOutlined";
import ReportProblemOutlinedIcon from "@mui/icons-material/ReportProblemOutlined";
import { Alert, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
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
  ["missing_ticket", "lostFound.redry.missingTicket"],
  ["wrong_pocket", "lostFound.redry.wrongPocket"],
];

function newRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `lf-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function NumberPicker({ label, options, value, onChange, optional = false }) {
  const { t } = useI18n();
  const theme = useTheme();
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
      <Typography variant="body2" sx={{ fontWeight: 700 }}>{label}</Typography>
      {options.length > 12 ? (
        <TextField
          size="small"
          value={query}
          placeholder={t("lostFound.searchNumber")}
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, maxHeight: 148, overflowY: "auto" }}>
        {shown.map((id) => {
          const selected = value === id;
          return (
            <Button
              key={id}
              type="button"
              variant={selected ? "contained" : "outlined"}
              onClick={() => onChange(id)}
              sx={{
                minWidth: 48,
                minHeight: 44,
                px: 1,
                py: 0.25,
                fontWeight: 700,
                textTransform: "none",
                borderColor: alpha(theme.palette.primary.main, 0.35),
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
    <Stack spacing={0.75}>
      <Typography variant="body2" sx={{ fontWeight: 700 }}>
        {t("lostFound.photos")} · {photos.length}
      </Typography>
      <Stack direction="row" spacing={0.75}>
        <Button type="button" variant="outlined" onClick={() => cameraRef.current?.click()} sx={{ flex: 1, minHeight: 44, textTransform: "none", fontWeight: 700 }}>
          {photos.length ? t("lostFound.addMore") : t("lostFound.takePhoto")}
        </Button>
        <Button type="button" variant="outlined" onClick={() => libraryRef.current?.click()} sx={{ flex: 1, minHeight: 44, textTransform: "none", fontWeight: 700 }}>
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
        <Stack direction="row" spacing={0.75} sx={{ overflowX: "auto" }}>
          {urls.map((photo) => (
            <Box key={photo.id} sx={{ width: 84, flexShrink: 0 }}>
              <Box component="img" src={photo.url} alt="" sx={{ width: 84, height: 84, objectFit: "cover", borderRadius: 1, display: "block" }} />
              <Stack direction="row" spacing={0.25}>
                <Button type="button" size="small" sx={{ minWidth: 0, minHeight: 44, px: 0.5, textTransform: "none" }} onClick={() => { replaceId.current = photo.id; replaceRef.current?.click(); }}>
                  {t("lostFound.retake")}
                </Button>
                <Button type="button" size="small" sx={{ minWidth: 0, minHeight: 44, px: 0.5, textTransform: "none" }} onClick={() => { replaceId.current = photo.id; libraryReplaceRef.current?.click(); }}>
                  {t("lostFound.replacePhoto")}
                </Button>
                <Button type="button" size="small" color="inherit" sx={{ minWidth: 0, minHeight: 44, px: 0.5, textTransform: "none" }} onClick={() => onChange(removeReportPhoto(photos, photo.id))}>
                  {t("lostFound.deletePhoto")}
                </Button>
              </Stack>
            </Box>
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}

export default function LostFoundReportForm({ choices, submitting, onSubmit }) {
  const { t } = useI18n();
  const theme = useTheme();
  const requestId = useRef(newRequestId());
  const [category, setCategory] = useState("");
  const [kind, setKind] = useState("");
  const [number, setNumber] = useState("");
  const [detail, setDetail] = useState("");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState([]);
  const [flags, setFlags] = useState({ missing_ticket: false, mesh_bag: false, wrong_pocket: false });
  const [error, setError] = useState("");

  const pocketOptions = (choices?.redry_pockets || []).length ? choices.redry_pockets : (choices?.dryers || []);
  const dryerRequired = category === "redry" && flags.wrong_pocket;
  const numberOptions = category === "redry"
    ? pocketOptions
    : identifierChoices(kind, choices);
  const needsNumber = dryerRequired
    || (category === "equipment" && kind && kind !== "other")
    || (category === "orphan" && ["washer", "dryer", "folding_table"].includes(kind));
  const numberOptional = (category === "orphan" && kind === "cart") || (category === "equipment" && kind === "other");

  const resetDetails = () => {
    setKind("");
    setNumber("");
    setDetail("");
    setFlags({ missing_ticket: false, mesh_bag: false, wrong_pocket: false });
    setError("");
  };

  const submit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    if (!photos.length) {
      setError(t("lostFound.photoRequired"));
      return;
    }
    if (category === "redry") {
      if (!Object.values(flags).some(Boolean)) {
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

  return (
    <Stack component="form" spacing={1} onSubmit={submit}>
      {error ? <Alert severity="warning">{error}</Alert> : null}
      {!category ? (
        <Stack spacing={0.75}>
          {CATEGORIES.map(([id, title, , Icon]) => (
            <Button
              key={id}
              type="button"
              variant="outlined"
              onClick={() => {
                setCategory(id);
                resetDetails();
                if (id === "redry") setKind("dryer");
              }}
              sx={{
                justifyContent: "flex-start",
                textAlign: "left",
                textTransform: "none",
                minHeight: 48,
                px: 1.25,
                py: 0.75,
                borderColor: alpha(theme.palette.primary.main, 0.35),
                color: "text.primary",
              }}
            >
              <Icon sx={{ mr: 1.25, color: "primary.main" }} />
              <Box>
                <Typography sx={{ fontWeight: 800, lineHeight: 1.25, fontSize: "1rem" }}>{t(title)}</Typography>
              </Box>
            </Button>
          ))}
        </Stack>
      ) : (
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography sx={{ fontWeight: 800, flex: 1, minWidth: 0 }}>{t(CATEGORIES.find(([id]) => id === category)[1])}</Typography>
          <Button type="button" size="small" onClick={() => { setCategory(""); resetDetails(); }} sx={{ textTransform: "none" }}>
            {t("lostFound.changeCategory")}
          </Button>
        </Stack>
      )}

      {category === "redry" ? (
        <Stack spacing={0.5}>
          {REDRY_FLAGS.map(([id, key]) => (
            <Button
              key={id}
              type="button"
              variant={flags[id] ? "contained" : "outlined"}
              onClick={() => setFlags((current) => {
                const next = { ...current, [id]: !current[id] };
                if (id === "wrong_pocket" && !next.wrong_pocket) setNumber("");
                return next;
              })}
              sx={{ minHeight: 48, justifyContent: "flex-start", textTransform: "none", fontWeight: 700, textAlign: "left", lineHeight: 1.25 }}
            >
              {t(key)}
            </Button>
          ))}
        </Stack>
      ) : null}

      {category === "orphan" ? (
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={0.5}>
          {FOUND_PLACES.map((id) => (
            <Button
              key={id}
              type="button"
              size="small"
              variant={kind === id ? "contained" : "outlined"}
              onClick={() => { setKind(id); setNumber(""); setDetail(""); }}
              sx={{ textTransform: "none", minHeight: 44 }}
            >
              {t(`lostFound.location.${id}`)}
            </Button>
          ))}
        </Stack>
      ) : null}

      {category === "equipment" ? (
        <Stack direction="row" flexWrap="wrap" useFlexGap spacing={0.5}>
          {EQUIPMENT_TYPES.map((id) => (
            <Button
              key={id}
              type="button"
              size="small"
              variant={kind === id ? "contained" : "outlined"}
              onClick={() => { setKind(id); setNumber(""); setDetail(""); }}
              sx={{ textTransform: "none", minHeight: 44 }}
            >
              {t(`lostFound.location.${id}`)}
            </Button>
          ))}
        </Stack>
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
          <TextField size="small" label={t("lostFound.notes")} value={notes} onChange={(event) => setNotes(event.target.value)} helperText={t("lostFound.optional")} />
          <Button type="submit" variant="contained" disabled={submitting} sx={{ minHeight: 44, fontWeight: 800, textTransform: "none" }}>
            {submitting ? t("lostFound.submitting") : t("lostFound.submit")}
          </Button>
        </>
      ) : null}
    </Stack>
  );
}
