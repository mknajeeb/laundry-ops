import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { getTeamStatus } from "../api";
import { useI18n } from "../i18n/I18nContext";
import { formatEmployeeAssignmentLabel, translateCanonicalRoleLabel } from "./mobileOpsCopy";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";

function etTodayYmd() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function shiftYmd(ymd, deltaDays) {
  const [y, m, d] = String(ymd).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + deltaDays);
  return dt.toISOString().slice(0, 10);
}

function formatDateLabel(ymd, locale) {
  const [y, m, d] = String(ymd).split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString(locale === "es" ? "es-US" : "en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTime(iso, locale) {
  if (!iso) return "—";
  const raw = String(iso).includes("T") ? String(iso) : String(iso).replace(" ", "T");
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) {
    // naive ET wall — parse as local-ish display from string
    const m = String(iso).match(/(\d{1,2}):(\d{2})/);
    if (!m) return "—";
    let h = Number(m[1]);
    const min = m[2];
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${h}:${min} ${ampm}`;
  }
  return dt.toLocaleTimeString(locale === "es" ? "es-US" : "en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDuration(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h <= 0) return `${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

function formatHoursCompact(sec) {
  const s = Math.max(0, Number(sec) || 0);
  const hrs = s / 3600;
  return hrs.toFixed(hrs >= 10 ? 1 : 1);
}

function localizeAssignment(empOrEv, t) {
  const src = empOrEv?.assignment || empOrEv || {};
  const label = formatEmployeeAssignmentLabel(
    {
      roleCode: src.role_code || empOrEv?.role_code,
      roleName: src.role_name,
      categoryCode: src.category_code || empOrEv?.category_code,
      categoryName: src.category_name,
    },
    t,
  );
  return label || src.assignment_label || empOrEv?.assignment_label || "";
}

function localizeRoleSummaryLabel(row, t) {
  if (row?.kind === "break") return t("mobileOps.team.break");
  return translateCanonicalRoleLabel(row?.label, t) || row?.label || "";
}

function statusChip(emp, t) {
  if (emp.status === "on_break" || emp.on_break) {
    return { label: t("mobileOps.team.onBreak"), color: "#b45309" };
  }
  if (emp.status === "working") {
    return { label: t("mobileOps.team.working"), color: OPS_MOBILE.success };
  }
  return { label: t("mobileOps.team.clockedOut"), color: OPS_MOBILE.muted };
}

function EmployeeCard({ emp, onOpen, t, locale, emphasize }) {
  const chip = statusChip(emp, t);
  return (
    <Box
      component="button"
      type="button"
      onClick={() => onOpen(emp)}
      sx={{
        display: "block",
        width: "100%",
        textAlign: "left",
        m: 0,
        p: { xs: 1.25, sm: 1.35 },
        borderRadius: `${OPS_MOBILE.radius.card}px`,
        border: `1px solid ${
          emphasize ? alpha(OPS_MOBILE.success, 0.35) : alpha(OPS_MOBILE.navy, 0.1)
        }`,
        bgcolor: emphasize ? alpha(OPS_MOBILE.success, 0.08) : alpha("#fff", 0.96),
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        minHeight: 72,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 900, fontSize: { xs: "1.02rem", sm: "1.08rem" }, color: OPS_MOBILE.navy }}>
            {emp.display_name}
          </Typography>
          {localizeAssignment(emp, t) ? (
            <Typography sx={{ fontWeight: 700, fontSize: "0.88rem", color: OPS_MOBILE.blue, mt: 0.2 }}>
              {localizeAssignment(emp, t)}
            </Typography>
          ) : null}
        </Box>
        {emphasize ? (
          <Chip
            size="small"
            label={chip.label}
            sx={{
              fontWeight: 800,
              bgcolor: alpha(chip.color, 0.14),
              color: chip.color,
              height: 26,
            }}
          />
        ) : null}
      </Stack>
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mt: 0.75, flexWrap: "wrap" }}>
        <Typography sx={{ fontSize: "0.82rem", fontWeight: 700, color: OPS_MOBILE.muted }}>
          {emphasize
            ? `${t("mobileOps.team.in")} ${formatTime(emp.clock_in_at, locale)}`
            : `${formatTime(emp.clock_in_at, locale)} – ${formatTime(emp.clock_out_at, locale)}`}
        </Typography>
        {emphasize && (emp.on_break || emp.status === "on_break") ? (
          <Typography sx={{ fontSize: "0.78rem", fontWeight: 900, color: chip.color }}>
            {t("mobileOps.team.onBreak").toUpperCase()}
          </Typography>
        ) : null}
        <Typography sx={{ fontSize: "0.88rem", fontWeight: 800, color: OPS_MOBILE.navy }}>
          {formatDuration(emp.worked_seconds)}
        </Typography>
      </Stack>
      {!emphasize && Array.isArray(emp.role_summary) && emp.role_summary.length ? (
        <Typography sx={{ mt: 0.5, fontSize: "0.78rem", fontWeight: 650, color: OPS_MOBILE.muted }}>
          {emp.role_summary
            .filter((r) => r.kind === "role")
            .map((r) => `${localizeRoleSummaryLabel(r, t)} · ${formatDuration(r.duration_seconds)}`)
            .join("  ")}
        </Typography>
      ) : null}
    </Box>
  );
}

function TimelineDrawer({ emp, open, onClose, t, locale, mobile }) {
  if (!emp) return null;
  return (
    <Drawer
      anchor={mobile ? "bottom" : "right"}
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: mobile ? "100%" : { sm: 420, md: 460 },
          maxHeight: mobile ? "88dvh" : "100%",
          borderTopLeftRadius: mobile ? 16 : 0,
          borderTopRightRadius: mobile ? 16 : 0,
          p: { xs: 2, sm: 2.25 },
          bgcolor: OPS_MOBILE.mist,
        },
      }}
    >
      <Stack spacing={1.5} sx={{ pb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography sx={{ fontWeight: 900, fontSize: "1.25rem", color: OPS_MOBILE.navy }}>
            {emp.display_name}
          </Typography>
          <Button onClick={onClose} sx={{ textTransform: "none", fontWeight: 800 }}>
            {t("mobileOps.done")}
          </Button>
        </Stack>
        <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.blue }}>
          {t("mobileOps.team.totalWorked")}: {formatDuration(emp.worked_seconds)}
        </Typography>

        <Stack spacing={1}>
          {(emp.timeline || []).map((ev, idx) => {
            if (ev.type === "clock_in") {
              return (
                <Typography key={`ci-${idx}`} sx={{ fontWeight: 700, fontSize: "0.92rem" }}>
                  {formatTime(ev.at, locale)} {t("mobileOps.team.clockedIn")}
                </Typography>
              );
            }
            if (ev.type === "clock_out") {
              return (
                <Typography key={`co-${idx}`} sx={{ fontWeight: 700, fontSize: "0.92rem" }}>
                  {formatTime(ev.at, locale)} {t("mobileOps.team.clockedOut")}
                </Typography>
              );
            }
            if (ev.type === "break") {
              return (
                <Box
                  key={`br-${idx}`}
                  sx={{
                    p: 1.1,
                    borderRadius: 2,
                    bgcolor: alpha("#b45309", 0.08),
                    border: `1px solid ${alpha("#b45309", 0.2)}`,
                  }}
                >
                  <Typography sx={{ fontWeight: 800, fontSize: "0.9rem" }}>
                    {formatTime(ev.started_at, locale)}
                    {ev.ended_at ? ` – ${formatTime(ev.ended_at, locale)}` : ""}
                  </Typography>
                  <Typography sx={{ fontWeight: 700, color: "#b45309", fontSize: "0.88rem" }}>
                    {t("mobileOps.team.break")} · {formatDuration(ev.duration_seconds)}
                    {ev.open ? ` · ${t("mobileOps.team.onBreak")}` : ""}
                  </Typography>
                </Box>
              );
            }
            return (
              <Box
                key={`role-${idx}`}
                sx={{
                  p: 1.1,
                  borderRadius: 2,
                  bgcolor: alpha("#fff", 0.95),
                  border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                }}
              >
                <Typography sx={{ fontWeight: 800, fontSize: "0.9rem", color: OPS_MOBILE.muted }}>
                  {formatTime(ev.started_at, locale)}
                  {ev.ended_at ? ` – ${formatTime(ev.ended_at, locale)}` : ` – ${t("mobileOps.team.now")}`}
                </Typography>
                <Typography sx={{ fontWeight: 800, color: OPS_MOBILE.navy }}>
                  {localizeAssignment(ev, t) || "—"}
                </Typography>
                <Typography sx={{ fontWeight: 700, fontSize: "0.88rem", color: OPS_MOBILE.blue }}>
                  {formatDuration(ev.duration_seconds)}
                </Typography>
              </Box>
            );
          })}
        </Stack>

        {(emp.role_summary || []).length ? (
          <Box sx={{ pt: 1 }}>
            <Typography sx={{ fontWeight: 900, mb: 0.75, color: OPS_MOBILE.navy }}>
              {t("mobileOps.team.roleSummary")}
            </Typography>
            <Stack spacing={0.5}>
              {emp.role_summary.map((row) => (
                <Stack
                  key={`${row.kind}-${row.label}`}
                  direction="row"
                  justifyContent="space-between"
                  sx={{ px: 0.25 }}
                >
                  <Typography sx={{ fontWeight: 700 }}>
                    {localizeRoleSummaryLabel(row, t)}
                  </Typography>
                  <Typography sx={{ fontWeight: 800 }}>{formatDuration(row.duration_seconds)}</Typography>
                </Stack>
              ))}
            </Stack>
          </Box>
        ) : null}
      </Stack>
    </Drawer>
  );
}

export default function TeamStatusFlow({ onBack, onLock }) {
  const { t, locale } = useI18n();
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [dateEt, setDateEt] = useState(() => etTodayYmd());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  const todayEt = useMemo(() => etTodayYmd(), []);
  const isToday = dateEt === todayEt;

  const load = useCallback(async (day) => {
    setLoading(true);
    setError("");
    try {
      const res = await getTeamStatus(day);
      setData(res.data || null);
    } catch (e) {
      setData(null);
      setError(e?.response?.data?.error || e?.message || t("mobileOps.team.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load(dateEt);
  }, [dateEt, load]);

  const summary = data?.summary || {};
  const working = data?.working_now || [];
  const worked = data?.worked || [];

  return (
    <OpsMobileShell
      maxWidth={720}
      sx={{ px: { xs: 1.5, sm: 2, md: 3 }, py: { xs: 1.5, sm: 2 } }}
    >
      <OpsTopBar
        title={t("mobileOps.team.title")}
        onBack={onBack}
        backLabel={t("mobileOps.backPin")}
        onLock={onLock}
        lockLabel={t("mobileOps.lock")}
        right={<OpsLocaleToggle />}
        sticky
      />

      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        spacing={1}
        sx={{
          mb: 1.25,
          p: 0.75,
          borderRadius: `${OPS_MOBILE.radius.button}px`,
          bgcolor: alpha("#fff", 0.9),
          border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
        }}
      >
        <IconButton
          aria-label={t("mobileOps.team.prevDay")}
          onClick={() => setDateEt((d) => shiftYmd(d, -1))}
          sx={{ minWidth: 44, minHeight: 44 }}
        >
          <ChevronLeftIcon />
        </IconButton>
        <Box sx={{ textAlign: "center", minWidth: 0 }}>
          <Typography sx={{ fontWeight: 900, color: OPS_MOBILE.navy, fontSize: { xs: "1rem", sm: "1.05rem" } }}>
            {formatDateLabel(dateEt, locale)}
          </Typography>
          {!isToday ? (
            <Button
              size="small"
              onClick={() => setDateEt(todayEt)}
              sx={{ textTransform: "none", fontWeight: 800, mt: 0.25, minHeight: 36 }}
            >
              {t("mobileOps.team.today")}
            </Button>
          ) : null}
        </Box>
        <IconButton
          aria-label={t("mobileOps.team.nextDay")}
          onClick={() => setDateEt((d) => shiftYmd(d, 1))}
          disabled={dateEt >= todayEt}
          sx={{ minWidth: 44, minHeight: 44 }}
        >
          <ChevronRightIcon />
        </IconButton>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 1.25 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <Box sx={{ py: 6, display: "grid", placeItems: "center" }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <>
          <Stack
            direction="row"
            spacing={1}
            sx={{
              mb: 1.5,
              flexWrap: "wrap",
              rowGap: 0.75,
            }}
          >
            {isToday ? (
              <Typography sx={{ fontWeight: 800, fontSize: "0.92rem", color: OPS_MOBILE.navy }}>
                <Box component="span" sx={{ color: OPS_MOBILE.success, fontWeight: 900 }}>
                  {summary.working_count ?? 0}
                </Box>{" "}
                {t("mobileOps.team.working")}
              </Typography>
            ) : null}
            <Typography sx={{ fontWeight: 800, fontSize: "0.92rem", color: OPS_MOBILE.navy }}>
              <Box component="span" sx={{ fontWeight: 900 }}>
                {summary.worked_count ?? 0}
              </Box>{" "}
              {isToday ? t("mobileOps.team.workedToday") : t("mobileOps.team.worked")}
            </Typography>
            <Typography sx={{ fontWeight: 800, fontSize: "0.92rem", color: OPS_MOBILE.navy }}>
              <Box component="span" sx={{ fontWeight: 900 }}>
                {formatHoursCompact(summary.total_worked_seconds)}
              </Box>{" "}
              {t("mobileOps.team.totalHours")}
            </Typography>
          </Stack>

          {isToday ? (
            <Box sx={{ mb: 2 }}>
              <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy }}>
                {t("mobileOps.team.workingNow")} · {working.length}
              </Typography>
              <Stack spacing={1}>
                {!working.length ? (
                  <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 650, fontSize: 13 }}>
                    {t("mobileOps.team.noneWorking")}
                  </Typography>
                ) : (
                  working.map((emp) => (
                    <EmployeeCard
                      key={`w-${emp.user_id}`}
                      emp={emp}
                      onOpen={setSelected}
                      t={t}
                      locale={locale}
                      emphasize
                    />
                  ))
                )}
              </Stack>
            </Box>
          ) : null}

          <Box sx={{ mb: 2 }}>
            <Typography sx={{ fontWeight: 900, mb: 1, color: OPS_MOBILE.navy }}>
              {isToday ? t("mobileOps.team.workedToday") : t("mobileOps.team.worked")} · {worked.length}
            </Typography>
            <Stack spacing={1}>
              {!worked.length ? (
                <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 650, fontSize: 13 }}>
                  {t("mobileOps.team.noneWorked")}
                </Typography>
              ) : (
                worked.map((emp) => (
                  <EmployeeCard
                    key={`d-${emp.user_id}`}
                    emp={emp}
                    onOpen={setSelected}
                    t={t}
                    locale={locale}
                    emphasize={false}
                  />
                ))
              )}
            </Stack>
          </Box>

          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </>
      )}

      <TimelineDrawer
        emp={selected}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        t={t}
        locale={locale}
        mobile={mobile}
      />
    </OpsMobileShell>
  );
}
