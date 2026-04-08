import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { DescriptionOutlined, Refresh } from "@mui/icons-material";
import { exportOrgDocumentRecordsZip, getHrFormsOrgSummary, getOrgDocumentRecords } from "../api";
import { hrModule } from "../components/hr/hrModuleStyles";
import { useI18n } from "../i18n/I18nContext";

function parseLocalDate(s) {
  if (!s) return null;
  const d = new Date(String(s).slice(0, 10));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Status tier from completeness and expiry (green / amber / red / gray). */
function documentRecordStatus(row, reminderDays) {
  const rd = Math.max(0, Number(reminderDays) || 14);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exp = parseLocalDate(row.expires_on);
  const st = String(row.status || "").toLowerCase();
  if (st === "expired") return { tier: "red", labelKey: "documents.tierExpired" };
  if (exp) {
    const exp0 = new Date(exp);
    exp0.setHours(0, 0, 0, 0);
    if (exp0 < today) return { tier: "red", labelKey: "documents.tierExpired" };
    const soon = new Date(today);
    soon.setDate(soon.getDate() + rd);
    if (exp0 <= soon) return { tier: "amber", labelKey: "documents.tierExpiringSoon" };
  }
  if (st === "rejected") return { tier: "red", labelKey: "documents.tierRejected" };
  if (st === "pending") return { tier: "amber", labelKey: "documents.tierPending" };
  if (st === "verified") return { tier: "green", labelKey: "documents.tierVerified" };
  if (st === "received") {
    if (String(row.source_kind || "").toLowerCase() === "generated") {
      return { tier: "green", labelKey: "documents.tierGenerated" };
    }
    if (row.file_uri) return { tier: "green", labelKey: "documents.tierReceived" };
    return { tier: "amber", labelKey: "documents.tierNeedsFile" };
  }
  return { tier: "gray", labelKey: "documents.tierOther" };
}

function evidenceFromRow(row) {
  const m = row.metadata_json;
  if (!m || typeof m !== "object") return { hasUri: false, uri: "", note: "" };
  const uri = m.evidence_uri != null ? String(m.evidence_uri).trim() : "";
  const note = m.evidence_note != null ? String(m.evidence_note).trim() : "";
  return { hasUri: !!uri, uri, note };
}

function rowMatchesEvidenceTab(r) {
  const ev = evidenceFromRow(r);
  if (ev.hasUri || ev.note) return true;
  if (r.evidence_required) return true;
  const m = r.metadata_json;
  if (m && typeof m === "object" && (m.requires_evidence || m.evidence_required)) return true;
  return false;
}

const EXPORT_ZIP_MAX = 120;

async function saveZipExportBlob(res, fallbackName) {
  const blob = res.data;
  if (!(blob instanceof Blob)) return { ok: false, error: "Invalid response" };
  const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
  const looksZip = head[0] === 0x50 && head[1] === 0x4b;
  if (!looksZip) {
    const text = await blob.text();
    try {
      const j = JSON.parse(text);
      return { ok: false, error: typeof j.error === "string" ? j.error : "Export failed" };
    } catch {
      return { ok: false, error: text.trim().slice(0, 240) || "Export failed" };
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fallbackName;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  return { ok: true };
}

function StatusChip({ row, reminderDays, t }) {
  const { tier, labelKey } = documentRecordStatus(row, reminderDays);
  const color = tier === "green" ? "success" : tier === "red" ? "error" : tier === "amber" ? "warning" : "default";
  return <Chip size="small" color={color} variant={tier === "gray" ? "outlined" : "filled"} label={t(labelKey)} />;
}

export default function DocumentsEvidencePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [employees, setEmployees] = useState([]);
  const [records, setRecords] = useState([]);
  const [reminderDays, setReminderDays] = useState(14);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("generated");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterLocale, setFilterLocale] = useState("");
  const [filterCode, setFilterCode] = useState("");
  const [zipBusy, setZipBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [sumRes, docRes] = await Promise.all([getHrFormsOrgSummary(), getOrgDocumentRecords()]);
      setEmployees(Array.isArray(sumRes.data) ? sumRes.data : []);
      const pack = docRes.data && typeof docRes.data === "object" ? docRes.data : {};
      setRecords(Array.isArray(pack.items) ? pack.items : []);
      setReminderDays(Number(pack.reminder_days_before) || 14);
    } catch (e) {
      setEmployees([]);
      setRecords([]);
      setError(e?.response?.data?.error || e?.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const q = search.trim().toLowerCase();
  const baseRecords = useMemo(() => {
    let list = records;
    if (filterStatus) list = list.filter((r) => String(r.status || "") === filterStatus);
    if (filterLocale) list = list.filter((r) => String(r.form_locale || "").toLowerCase() === filterLocale);
    if (filterCode.trim())
      list = list.filter(
        (r) =>
          String(r.document_code || "")
            .toLowerCase()
            .includes(filterCode.trim().toLowerCase()) ||
          String(r.document_name || "")
            .toLowerCase()
            .includes(filterCode.trim().toLowerCase()),
      );
    if (!q) return list;
    return list.filter((r) => {
      const blob = [
        r.employee_display_name,
        r.emp_employee_id,
        r.emp_email,
        r.washpro_username,
        r.document_code,
        r.document_name,
        String(r.user_id),
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [records, q, filterStatus, filterLocale, filterCode]);

  const tabRecords = useMemo(() => {
    if (tab === "generated") return baseRecords.filter((r) => r.source_kind === "generated");
    if (tab === "uploaded") return baseRecords.filter((r) => r.source_kind === "uploaded" || r.source_kind === "external");
    if (tab === "evidence") return baseRecords.filter(rowMatchesEvidenceTab);
    return baseRecords;
  }, [baseRecords, tab]);

  const exportFilteredZip = async () => {
    const ids = tabRecords.map((r) => Number(r.id)).filter((n) => Number.isFinite(n) && n > 0);
    if (!ids.length) {
      setError(t("documents.exportZipNoRows"));
      return;
    }
    if (ids.length > EXPORT_ZIP_MAX) {
      setError(t("documents.exportZipTooMany"));
      return;
    }
    setError("");
    setZipBusy(true);
    try {
      const res = await exportOrgDocumentRecordsZip(ids);
      const name = `documents-${ids.length}-rows.zip`;
      const out = await saveZipExportBlob(res, name);
      if (!out.ok) setError(out.error || t("documents.exportZipFailed"));
    } catch (e) {
      const raw = e?.response?.data;
      if (raw instanceof Blob) {
        const text = await raw.text();
        try {
          const j = JSON.parse(text);
          setError(typeof j.error === "string" ? j.error : t("documents.exportZipFailed"));
        } catch {
          setError(text.trim().slice(0, 240) || t("documents.exportZipFailed"));
        }
      } else {
        setError(e?.response?.data?.error || e?.message || t("documents.exportZipFailed"));
      }
    } finally {
      setZipBusy(false);
    }
  };

  const filteredEmployees = useMemo(() => {
    if (!q) return employees;
    return employees.filter((r) => {
      const blob = [r.name, r.email, r.employee_id, String(r.user_id), (r.lanes_detected || []).join(" ")]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [employees, q]);

  const localeChoices = useMemo(() => {
    const s = new Set();
    for (const r of records) {
      const L = String(r.form_locale || "").trim();
      if (L) s.add(L.toLowerCase());
    }
    return Array.from(s).sort();
  }, [records]);

  return (
    <Box sx={hrModule.pageCanvas}>
      <Box sx={hrModule.contentMax}>
        <Paper elevation={0} sx={hrModule.hero}>
          <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "flex-start" }} justifyContent="space-between" spacing={2}>
            <Box sx={{ display: "flex", gap: 1.5, alignItems: "flex-start" }}>
              <Box
                sx={{
                  width: 48,
                  height: 48,
                  borderRadius: 2,
                  bgcolor: "rgba(255,255,255,0.2)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <DescriptionOutlined sx={{ fontSize: 28, opacity: 0.95 }} />
              </Box>
              <Box>
                <Typography sx={hrModule.heroOverline}>{t("documents.pageKicker")}</Typography>
                <Typography variant="h4" component="h1" sx={hrModule.heroTitle}>
                  {t("documents.title")}
                </Typography>
                <Typography variant="body2" sx={hrModule.heroSubtitle}>
                  {t("documents.subtitle")}
                </Typography>
                <Typography variant="caption" sx={{ opacity: 0.88, display: "block", mt: 1.25, lineHeight: 1.5 }}>
                  {t("documents.statusLegend")}
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 2 }}>
                  <Chip
                    size="small"
                    label={t("documents.statInTab").replace("{n}", String(tabRecords.length))}
                    sx={hrModule.statChip}
                  />
                  <Chip
                    size="small"
                    label={t("documents.statCatalog").replace("{n}", String(records.length))}
                    sx={hrModule.statChip}
                  />
                </Stack>
              </Box>
            </Box>
          </Stack>
        </Paper>

        {error ? (
          <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }} onClose={() => setError("")}>
            {error}
          </Alert>
        ) : null}

        <Paper elevation={0} sx={(theme) => hrModule.filterBar(theme)}>
          <Stack spacing={2}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, letterSpacing: "-0.01em" }}>
              {t("documents.filterPanelTitle")}
            </Typography>
            <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} flexWrap="wrap" useFlexGap alignItems={{ lg: "center" }}>
              <TextField
                size="small"
                label={t("documents.filterEmployeeSearch")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                sx={{ minWidth: 240, flex: { lg: "1 1 220px" } }}
              />
              <FormControl size="small" sx={{ minWidth: 160 }}>
                <InputLabel>{t("documents.filterDocStatus")}</InputLabel>
                <Select
                  label={t("documents.filterDocStatus")}
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                >
                  <MenuItem value="">{t("people.all")}</MenuItem>
                  <MenuItem value="pending">pending</MenuItem>
                  <MenuItem value="received">received</MenuItem>
                  <MenuItem value="verified">verified</MenuItem>
                  <MenuItem value="expired">expired</MenuItem>
                  <MenuItem value="rejected">rejected</MenuItem>
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>{t("documents.filterLanguage")}</InputLabel>
                <Select label={t("documents.filterLanguage")} value={filterLocale} onChange={(e) => setFilterLocale(e.target.value)}>
                  <MenuItem value="">{t("people.all")}</MenuItem>
                  {localeChoices.map((lc) => (
                    <MenuItem key={lc} value={lc}>
                      {lc}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                size="small"
                label={t("documents.filterFormCode")}
                value={filterCode}
                onChange={(e) => setFilterCode(e.target.value)}
                sx={{ minWidth: 160 }}
              />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ ml: { lg: "auto" } }}>
                <Button variant="outlined" size="medium" onClick={load} startIcon={<Refresh />}>
                  {t("common.refresh")}
                </Button>
                <Button
                  variant="contained"
                  size="medium"
                  disabled={zipBusy || !tabRecords.length}
                  onClick={exportFilteredZip}
                  startIcon={zipBusy ? <CircularProgress size={16} color="inherit" /> : null}
                >
                  {t("documents.exportZip")}
                </Button>
              </Stack>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {t("documents.exportZipHint")}
            </Typography>
          </Stack>
        </Paper>

        <Paper elevation={0} sx={(theme) => ({ ...hrModule.tableCard(theme), mt: 2, overflow: "hidden" })}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={(theme) => hrModule.tabs(theme)}>
            <Tab value="generated" label={t("documents.tabGenerated")} />
            <Tab value="uploaded" label={t("documents.tabUploaded")} />
            <Tab value="evidence" label={t("documents.tabEvidence")} />
          </Tabs>
          {tab === "evidence" ? (
            <Box sx={{ px: 2, py: 1.5, bgcolor: (th) => (th.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : "grey.50"), borderBottom: 1, borderColor: "divider" }}>
              <Typography variant="body2" color="text.secondary">
                {t("documents.evidenceTabHint")}
              </Typography>
            </Box>
          ) : null}

          {tab === "generated" && !tabRecords.length ? (
            <Alert severity="info" sx={{ m: 2, borderRadius: 2 }}>
              {t("documents.generatedEmpty")}
            </Alert>
          ) : null}

          {!tabRecords.length ? (
            <Box sx={{ py: 6, px: 3, textAlign: "center" }}>
              <Typography variant="subtitle1" color="text.secondary" sx={{ fontWeight: 600 }}>
                {tab === "generated"
                  ? t("documents.useHubToGenerate")
                  : tab === "evidence"
                    ? t("documents.evidenceEmpty")
                    : t("documents.noRows")}
              </Typography>
            </Box>
          ) : (
            <Box
              sx={{
                p: 2,
                display: "grid",
                gap: 2,
                gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", lg: "repeat(3, minmax(0, 1fr))" },
              }}
            >
              {tabRecords.map((r) => {
                const ev = evidenceFromRow(r);
                return (
                  <Card
                    key={r.id}
                    variant="outlined"
                    sx={{
                      borderRadius: 3,
                      display: "flex",
                      flexDirection: "column",
                      borderColor: "divider",
                      boxShadow: (theme) => (theme.palette.mode === "dark" ? "none" : "0 2px 12px rgba(15,23,42,0.06)"),
                    }}
                  >
                    <CardContent sx={{ flex: 1, pt: 2 }}>
                      <Typography variant="overline" color="primary" sx={{ fontWeight: 700, letterSpacing: "0.06em" }}>
                        {r.document_code}
                      </Typography>
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, mt: 0.5, lineHeight: 1.35 }}>
                        {r.document_name || r.document_code}
                      </Typography>
                      <Divider sx={{ my: 1.5 }} />
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {r.employee_display_name || "—"}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t("people.colEmployeeId")}: {r.emp_employee_id || "—"} · {t("documents.colLanguage")}: {r.form_locale || "—"}
                      </Typography>
                      <Box sx={{ mt: 1.5 }}>
                        <StatusChip row={r} reminderDays={reminderDays} t={t} />
                        <Chip size="small" variant="outlined" label={r.source_kind || "—"} sx={{ ml: 0.75 }} />
                      </Box>
                      {tab === "evidence" ? (
                        <Box sx={{ mt: 1.25 }}>
                          {ev.hasUri ? (
                            <Chip size="small" color="success" label={t("documents.evidencePresent")} />
                          ) : (
                            <Chip size="small" color="warning" variant="outlined" label={t("documents.evidenceMissing")} />
                          )}
                          {ev.note ? (
                            <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.75 }}>
                              {ev.note}
                            </Typography>
                          ) : null}
                        </Box>
                      ) : null}
                      {tab !== "evidence" && (r.file_uri || r.notes) ? (
                        <Typography variant="caption" color="text.secondary" sx={{ mt: 1.25, display: "block", wordBreak: "break-word" }}>
                          {r.file_uri || r.notes}
                        </Typography>
                      ) : null}
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        {r.issued_on ? `${t("documents.colIssued")}: ${String(r.issued_on).slice(0, 10)}` : ""}
                        {r.issued_on && r.expires_on ? " · " : ""}
                        {r.expires_on ? `${t("documents.colExpires")}: ${String(r.expires_on).slice(0, 10)}` : ""}
                        {!r.issued_on && !r.expires_on ? "—" : ""}
                      </Typography>
                    </CardContent>
                    <CardActions sx={{ px: 2, pb: 2, pt: 0, flexWrap: "wrap", gap: 0.5 }}>
                      <Button size="small" variant="outlined" onClick={() => navigate(`/employees/${r.user_id}`)}>
                        {t("documents.openProfile")}
                      </Button>
                      <Button size="small" variant="contained" onClick={() => navigate(`/employees/${r.user_id}/hr`)}>
                        {t("documents.openHub")}
                      </Button>
                    </CardActions>
                  </Card>
                );
              })}
            </Box>
          )}
        </Paper>

        {tab === "generated" && filteredEmployees.length ? (
          <Box sx={{ mt: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: "-0.02em", mb: 0.5 }}>
              {t("documents.packetOverviewTitle")}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {t("documents.packetOverviewHint")}
            </Typography>
            <Box
              sx={{
                display: "grid",
                gap: 2,
                gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", md: "repeat(3, minmax(0, 1fr))" },
              }}
            >
              {filteredEmployees.map((r) => (
                <Card key={r.user_id} variant="outlined" sx={{ borderRadius: 3 }}>
                  <CardContent>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                      {r.name || "—"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {r.employee_id || "—"} · {r.email || "—"}
                    </Typography>
                    <Stack direction="row" flexWrap="wrap" gap={0.5} sx={{ mt: 1.25 }}>
                      {(r.lanes_detected || []).map((x) => (
                        <Chip key={x} label={x} size="small" variant="outlined" />
                      ))}
                    </Stack>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      {t("documents.colFormCount")}: <strong>{r.forms_count ?? 0}</strong>
                    </Typography>
                  </CardContent>
                  <CardActions sx={{ px: 2, pb: 2 }}>
                    <Button size="small" variant="contained" fullWidth onClick={() => navigate(`/employees/${r.user_id}/hr`)}>
                      {t("documents.openHub")}
                    </Button>
                  </CardActions>
                </Card>
              ))}
            </Box>
          </Box>
        ) : null}
      </Box>
    </Box>
  );
}
