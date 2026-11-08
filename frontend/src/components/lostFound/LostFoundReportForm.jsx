import { useMemo, useRef, useState } from "react";
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useI18n } from "../../i18n/I18nContext";

const REDRY_FLAGS = [
  ["missing_ticket", "lostFound.redry.missingTicket"],
  ["mesh_bag", "lostFound.redry.meshBag"],
  ["wrong_pocket", "lostFound.redry.wrongPocket"],
];

function newRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `lf-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function LostFoundReportForm({ choices, submitting, onSubmit }) {
  const { t } = useI18n();
  const requestId = useRef(newRequestId());
  const cameraRef = useRef(null);
  const [category, setCategory] = useState("");
  const [kind, setKind] = useState("");
  const [number, setNumber] = useState("");
  const [detail, setDetail] = useState("");
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState([]);
  const [flags, setFlags] = useState({ missing_ticket: false, mesh_bag: false, wrong_pocket: false });
  const [error, setError] = useState("");

  const numberOptions = useMemo(() => {
    if (category === "redry") {
      const pockets = choices?.redry_pockets || [];
      return pockets.length ? pockets : choices?.dryers || [];
    }
    if (kind === "washer") return choices?.washers || [];
    if (kind === "dryer") return choices?.dryers || [];
    if (kind === "folding_table") return choices?.folding_tables || [];
    return [];
  }, [category, choices, kind]);

  const needsNumber = category === "redry" || ["washer", "dryer", "folding_table"].includes(kind);
  const numberOptional = category !== "redry" && kind === "cart";
  const needsDetail = category !== "redry" && kind === "other";
  const previews = files.map((file) => ({ file, url: URL.createObjectURL(file) }));

  const addPhotos = (list) => {
    const next = Array.from(list || []).filter((file) => file && file.size > 0);
    if (!next.length) return;
    setFiles((current) => [...current, ...next].slice(0, 4));
    setError("");
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!files.length) {
      setError(t("lostFound.photoRequired"));
      return;
    }
    if (category === "redry") {
      if (!Object.values(flags).some(Boolean)) {
        setError(t("lostFound.redry.flagRequired"));
        return;
      }
      if (!String(number || "").trim()) {
        setError(t("lostFound.redry.pocketRequired"));
        return;
      }
    } else if (!kind) {
      setError(t("lostFound.error.invalid_location"));
      return;
    } else if (needsNumber && !String(number || "").trim()) {
      setError(t("lostFound.error.location_number_required"));
      return;
    } else if (needsDetail && String(detail || "").trim().length < 2) {
      setError(t("lostFound.error.location_detail_required"));
      return;
    }
    setError("");
    await onSubmit({
      client_request_id: requestId.current,
      report_category: category === "redry" ? "redry" : "orphan",
      location_kind: category === "redry" ? "dryer" : kind,
      location_number: number,
      location_detail: detail,
      notes,
      files,
      redry_missing_ticket: flags.missing_ticket,
      redry_mesh_bag: flags.mesh_bag,
      redry_wrong_pocket: flags.wrong_pocket,
    });
  };

  return (
    <Stack component="form" spacing={1.25} onSubmit={submit}>
      {error ? <Alert severity="warning">{error}</Alert> : null}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
        {[
          ["orphan", "lostFound.orphan"],
          ["redry", "lostFound.redryIssue"],
        ].map(([id, key]) => (
          <Button
            key={id}
            type="button"
            variant={category === id ? "contained" : "outlined"}
            onClick={() => {
              setCategory(id);
              setKind(id === "redry" ? "dryer" : "");
              setError("");
            }}
            sx={{ flex: 1, minHeight: 64, fontWeight: 900, textTransform: "none", fontSize: "1.05rem" }}
          >
            {t(key)}
          </Button>
        ))}
      </Stack>
      {category === "redry" ? (
        <Stack spacing={1}>
          {REDRY_FLAGS.map(([id, key]) => (
            <Button
              key={id}
              type="button"
              variant={flags[id] ? "contained" : "outlined"}
              color={flags[id] ? "warning" : "inherit"}
              onClick={() => setFlags((current) => ({ ...current, [id]: !current[id] }))}
              sx={{ minHeight: 56, justifyContent: "flex-start", textTransform: "none", fontWeight: 800 }}
            >
              {t(key)}
            </Button>
          ))}
        </Stack>
      ) : null}
      {category === "orphan" ? (
        <TextField select label={t("lostFound.location")} value={kind} onChange={(e) => { setKind(e.target.value); setNumber(""); }} required>
          {["washer", "dryer", "folding_table", "floor", "cart", "other"].map((id) => (
            <MenuItem key={id} value={id}>{t(`lostFound.location.${id}`)}</MenuItem>
          ))}
        </TextField>
      ) : null}
      {category && (needsNumber || numberOptional) ? (
        <TextField
          select={numberOptions.length > 0}
          label={category === "redry" ? t("lostFound.redry.pocket") : t(`lostFound.number.${kind || "cart"}`)}
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          required={needsNumber}
          helperText={numberOptional ? t("lostFound.optional") : ""}
        >
          {numberOptions.length ? [
            <MenuItem key="" value="">{t("lostFound.otherNumber")}</MenuItem>,
            ...numberOptions.map((id) => <MenuItem key={id} value={id}>{id}</MenuItem>),
          ] : null}
        </TextField>
      ) : null}
      {needsDetail ? (
        <TextField label={t("lostFound.otherDetail")} value={detail} onChange={(e) => setDetail(e.target.value)} required />
      ) : null}
      {category ? (
        <>
          <Stack direction="row" spacing={1}>
            <Button variant="outlined" onClick={() => cameraRef.current?.click()} sx={{ flex: 1, minHeight: 52, fontWeight: 900, textTransform: "none" }}>
              {t("lostFound.takePhoto")}
            </Button>
            <Button variant="text" component="label" sx={{ minHeight: 52, fontWeight: 800, textTransform: "none" }}>
              {t("lostFound.choosePhoto")}
              <input hidden type="file" accept="image/*" multiple onChange={(e) => { addPhotos(e.target.files); e.target.value = ""; }} />
            </Button>
          </Stack>
          <input ref={cameraRef} hidden type="file" accept="image/*" capture="environment" onChange={(e) => { addPhotos(e.target.files); e.target.value = ""; }} />
          {previews.length ? (
            <Stack direction="row" spacing={1} sx={{ overflowX: "auto" }}>
              {previews.map((preview, index) => (
                <Box key={`${preview.file.name}-${index}`} sx={{ position: "relative" }}>
                  <Box component="img" src={preview.url} alt="" sx={{ width: 92, height: 92, objectFit: "cover", borderRadius: 1 }} />
                  <Button size="small" onClick={() => setFiles((current) => current.filter((_, item) => item !== index))} sx={{ position: "absolute", top: 0, right: 0, minWidth: 0, color: "#fff" }}>
                    {t("lostFound.retake")}
                  </Button>
                </Box>
              ))}
            </Stack>
          ) : null}
          <TextField label={t("lostFound.notes")} value={notes} onChange={(e) => setNotes(e.target.value)} multiline minRows={2} />
          <Button type="submit" variant="contained" disabled={submitting} sx={{ minHeight: 56, fontWeight: 900, textTransform: "none", fontSize: "1.05rem" }}>
            {t("lostFound.submit")}
          </Button>
        </>
      ) : null}
    </Stack>
  );
}
