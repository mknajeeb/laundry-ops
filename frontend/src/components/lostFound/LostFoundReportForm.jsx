import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, MenuItem, Stack, TextField } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";
import {
  FOUND_LOCATION_KINDS,
  identifierChoices,
  locationNumberMode,
  validateFoundLocation,
} from "../../utils/lostFoundLocation";

function LocalPreview({ file }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  if (!url) return null;
  return <img alt="" src={url} style={{ width: 72, height: 72, objectFit: "cover", borderRadius: 8 }} />;
}

function newRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `lf-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function LostFoundReportForm({
  choices = {},
  submitting = false,
  onSubmit,
  submitLabel,
}) {
  const { t } = useI18n();
  const requestId = useRef(newRequestId());
  const cameraRef = useRef(null);
  const libraryRef = useRef(null);
  const [kind, setKind] = useState("");
  const [number, setNumber] = useState("");
  const [typedNumber, setTypedNumber] = useState("");
  const [detail, setDetail] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState([]);
  const [error, setError] = useState("");

  const mode = locationNumberMode(kind);
  const options = useMemo(() => identifierChoices(kind, choices), [kind, choices]);
  const showTyped = mode === "required" || mode === "optional"
    ? options.length === 0 || number === "__other__"
    : false;
  const selectedNumber = number === "__other__" ? typedNumber : number;

  const addFiles = (list) => {
    const next = [...files];
    for (const file of list || []) {
      if (file && String(file.type || "").startsWith("image/")) next.push(file);
    }
    setFiles(next.slice(0, 6));
  };

  const submit = () => {
    const code = validateFoundLocation({ kind, number: selectedNumber, detail });
    if (!files.length) {
      setError(t("lostFound.photoRequired"));
      return;
    }
    if (code) {
      setError(t(`lostFound.error.${code}`));
      return;
    }
    setError("");
    onSubmit?.({
      client_request_id: requestId.current,
      location_kind: kind,
      location_number: mode === "required" || mode === "optional" ? selectedNumber : "",
      location_detail: mode === "detail" ? detail : "",
      notes,
      files,
    });
  };

  return (
    <Stack spacing={1.25}>
      {error ? <Alert severity="warning">{error}</Alert> : null}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <input
        ref={libraryRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <Button variant="contained" onClick={() => cameraRef.current?.click()} sx={{ fontWeight: 800, textTransform: "none" }}>
        {t("lostFound.takePhoto")}
      </Button>
      <Button variant="outlined" onClick={() => libraryRef.current?.click()} sx={{ fontWeight: 800, textTransform: "none" }}>
        {t("lostFound.choosePhoto")}
      </Button>
      {files.length ? (
        <Stack direction="row" spacing={1} sx={{ overflowX: "auto" }}>
          {files.map((file, index) => (
            <LocalPreview key={`${file.name}-${file.size}-${index}`} file={file} />
          ))}
        </Stack>
      ) : null}
      <TextField
        select
        fullWidth
        label={t("lostFound.location")}
        value={kind}
        onChange={(e) => {
          setKind(e.target.value);
          setNumber("");
          setTypedNumber("");
          setDetail("");
        }}
      >
        <MenuItem value="">{t("lostFound.location")}</MenuItem>
        {FOUND_LOCATION_KINDS.map((code) => (
          <MenuItem key={code} value={code}>
            {t(`lostFound.location.${code}`)}
          </MenuItem>
        ))}
      </TextField>
      {options.length > 0 && (mode === "required" || mode === "optional") ? (
        <TextField
          select
          fullWidth
          label={t(`lostFound.number.${kind}`)}
          value={number}
          onChange={(e) => setNumber(e.target.value)}
        >
          <MenuItem value="">{mode === "optional" ? t("lostFound.optional") : "—"}</MenuItem>
          {options.map((code) => (
            <MenuItem key={code} value={code}>
              {code}
            </MenuItem>
          ))}
          <MenuItem value="__other__">{t("lostFound.otherNumber")}</MenuItem>
        </TextField>
      ) : null}
      {showTyped ? (
        <TextField
          fullWidth
          label={t(`lostFound.number.${kind}`)}
          value={typedNumber}
          onChange={(e) => setTypedNumber(e.target.value)}
          helperText={mode === "optional" ? t("lostFound.optional") : ""}
          inputProps={{ inputMode: "text", autoComplete: "off" }}
        />
      ) : null}
      {mode === "detail" ? (
        <TextField
          fullWidth
          label={t("lostFound.otherDetail")}
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          inputProps={{ maxLength: 160 }}
        />
      ) : null}
      <TextField
        fullWidth
        label={t("lostFound.notes")}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        helperText={t("lostFound.optional")}
        inputProps={{ maxLength: 1000 }}
      />
      <Button
        variant="contained"
        color="success"
        disabled={submitting || !kind}
        onClick={submit}
        sx={{ fontWeight: 900, textTransform: "none", py: 1.25 }}
      >
        {submitting ? t("lostFound.submitting") : submitLabel || t("lostFound.submit")}
      </Button>
    </Stack>
  );
}
