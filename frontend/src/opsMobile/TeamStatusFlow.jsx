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
import { getTeamStatus, getTeamStatusUpcoming, getTeamStatusWeek } from "../api";
import { useI18n } from "../i18n/I18nContext";
import {
  formatEmployeeAssignmentLabel,
  translateCanonicalRoleLabel,
  translateCanonicalWorkLabel,
} from "./mobileOpsCopy";
import {
  TEAM_ROLE_COLORS,
  resolveTeamRoleColorKey,
  teamRoleChipSx,
  teamRoleColors,
  teamRoleEdgeSx,
} from "./roleColors";
import OpsLocaleToggle from "./OpsLocaleToggle";
import OpsLockButton from "./OpsLockButton";
import OpsMobileShell from "./OpsMobileShell";
import OpsTopBar from "./OpsTopBar";
import { OPS_MOBILE } from "./tokens";

const GOLD = "#c4a052";
const TABS = ["today", "week", "upcoming"];

function RoleTintChip({ roleCode, roleLabel, kind, label, t, size = "sm" }) {
  const key = resolveTeamRoleColorKey({ roleCode, roleLabel, kind, label });
  const canonical =
    key === "wash_dry"
      ? "Wash-Dry"
      : key === "sort"
        ? "Sort"
        : key === "fold"
          ? "Fold"
          : key === "break"
            ? null
            : roleLabel || label || "";
  const text =
    key === "break"
      ? t("mobileOps.team.breakShort")
      : translateCanonicalRoleLabel(canonical || roleLabel || label, t) ||
        roleLabel ||
        label ||
        "—";
  return (
    <Chip
      size="small"
      label={text}
      sx={teamRoleChipSx({ roleCode, roleLabel: canonical || roleLabel, kind, label }, { size })}
    />
  );
}

function workTypeDisplay(empOrEv, t) {
  const src = empOrEv?.assignment || empOrEv || {};
  const raw = src.work_type_label || "";
  return translateCanonicalWorkLabel(raw, t) || raw;
}

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

function formatNavLabel(ymd, todayYmd, locale, t) {
  const [y, m, d] = String(ymd).split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const monthDay = dt.toLocaleDateString(locale === "es" ? "es-US" : "en-US", {
    month: "short",
    day: "numeric",
  });
  if (ymd === todayYmd) return `${t("mobileOps.team.today")} · ${monthDay}`;
  const weekday = dt.toLocaleDateString(locale === "es" ? "es-US" : "en-US", { weekday: "short" });
  return `${weekday} · ${monthDay}`;
}

function formatWeekRange(startYmd, endYmd, locale) {
  if (!startYmd || !endYmd) return "";
  const loc = locale === "es" ? "es-US" : "en-US";
  const [ys, ms, ds] = String(startYmd).split("-").map(Number);
  const [ye, me, de] = String(endYmd).split("-").map(Number);
  const start = new Date(ys, ms - 1, ds);
  const end = new Date(ye, me - 1, de);
  const month = start.toLocaleDateString(loc, { month: "short" });
  if (ms === me && ys === ye) {
    return `${month} ${ds}–${de}`;
  }
  const a = start.toLocaleDateString(loc, { month: "short", day: "numeric" });
  const b = end.toLocaleDateString(loc, { month: "short", day: "numeric" });
  return `${a}–${b}`;
}

function formatTime(iso, locale) {
  if (!iso) return "—";
  const raw = String(iso).includes("T") ? String(iso) : String(iso).replace(" ", "T");
  const dt = new Date(raw);
  if (Number.isNaN(dt.getTime())) {
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

function formatHhMm(hhmm, locale) {
  if (!hhmm) return "—";
  const m = String(hhmm).match(/(\d{1,2}):(\d{2})/);
  if (!m) return String(hhmm);
  let h = Number(m[1]);
  const min = m[2];
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  void locale;
  return `${h}:${min} ${ampm}`;
}

function formatDuration(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h <= 0) return `${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

function localizeAssignment(empOrEv, t) {
  const src = empOrEv?.assignment || empOrEv || {};
  const label = formatEmployeeAssignmentLabel(
    {
      roleCode: src.role_code || empOrEv?.role_code,
      roleName: src.role_name || src.role_label,
      categoryCode: src.category_code || empOrEv?.category_code,
      categoryName: src.category_name || src.work_type_label,
    },
    t,
  );
  return label || src.assignment_label || empOrEv?.assignment_label || "";
}

function statusMeta(emp, t) {
  if (emp.status === "on_break" || emp.on_break) {
    const c = TEAM_ROLE_COLORS.break;
    return { label: t("mobileOps.team.onBreak"), color: c.text, bg: c.bg };
  }
  if (emp.status === "working") {
    return { label: t("mobileOps.team.working"), color: OPS_MOBILE.success };
  }
  return { label: t("mobileOps.team.completed"), color: OPS_MOBILE.muted };
}

function TabBar({ tab, onChange, t }) {
  return (
    <Stack
      direction="row"
      spacing={0.5}
      sx={{
        mb: 1,
        p: 0.4,
        borderRadius: 2,
        bgcolor: alpha("#fff", 0.92),
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
      }}
    >
      {TABS.map((id) => {
        const active = tab === id;
        return (
          <Button
            key={id}
            onClick={() => onChange(id)}
            sx={{
              flex: 1,
              minHeight: 40,
              py: 0.75,
              textTransform: "none",
              fontWeight: 850,
              fontSize: "0.92rem",
              borderRadius: 1.5,
              color: active ? OPS_MOBILE.navy : OPS_MOBILE.muted,
              bgcolor: active ? alpha(GOLD, 0.18) : "transparent",
              border: active ? `1px solid ${alpha(GOLD, 0.45)}` : "1px solid transparent",
            }}
          >
            {t(`mobileOps.team.tab.${id}`)}
          </Button>
        );
      })}
    </Stack>
  );
}

function SummaryStrip({ items }) {
  return (
    <Box
      sx={{
        mb: 1.25,
        px: 1.1,
        py: 0.9,
        borderRadius: 2,
        bgcolor: alpha("#fff", 0.96),
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.1)}`,
        borderLeft: `3px solid ${GOLD}`,
        display: "grid",
        gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(4, auto)" },
        columnGap: { xs: 1, sm: 1.5 },
        rowGap: 0.45,
        alignItems: "center",
        justifyContent: { sm: "start" },
      }}
    >
      {items.map((it) => (
        <Typography
          key={it.key}
          sx={{
            fontWeight: 800,
            fontSize: "0.84rem",
            color: OPS_MOBILE.navy,
            whiteSpace: "nowrap",
          }}
        >
          <Box component="span" sx={{ color: it.color || OPS_MOBILE.navy, fontWeight: 950 }}>
            {it.value}
          </Box>{" "}
          <Box component="span" sx={{ color: OPS_MOBILE.muted, fontWeight: 700 }}>
            {it.label}
          </Box>
        </Typography>
      ))}
    </Box>
  );
}

function RoleCoverageLine({ title, parts, note, t }) {
  const [showHours, setShowHours] = useState(false);
  if (!parts?.length) return null;
  const visible = parts.filter((p) => (p.count ?? p.unique_employees ?? 0) > 0 || showHours);
  if (!visible.length) return null;
  return (
    <Box sx={{ mb: 0.85 }}>
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.35 }}>
        <Typography
          sx={{
            fontWeight: 900,
            fontSize: "0.68rem",
            letterSpacing: 0.6,
            color: GOLD,
            textTransform: "uppercase",
          }}
        >
          {title}
        </Typography>
        {note ? (
          <Typography
            component="button"
            type="button"
            onClick={() => setShowHours((v) => !v)}
            title={note}
            sx={{
              border: 0,
              background: "none",
              p: 0,
              m: 0,
              cursor: "pointer",
              fontSize: "0.68rem",
              fontWeight: 800,
              color: OPS_MOBILE.blue,
              textDecoration: "underline",
              fontFamily: "inherit",
            }}
          >
            {showHours ? t("mobileOps.team.hideRoleHours") : t("mobileOps.team.showRoleHours")}
          </Typography>
        ) : null}
      </Stack>
      <Stack direction="row" spacing={0.45} useFlexGap flexWrap="wrap" sx={{ rowGap: 0.45 }}>
        {visible.map((p) => {
          const n = p.count ?? p.unique_employees ?? 0;
          const isBreak = p.label === "Break";
          const hoursBit =
            showHours && p.duration_seconds != null ? ` · ${formatDuration(p.duration_seconds)}` : "";
          return (
            <Chip
              key={p.label}
              size="small"
              label={`${
                isBreak
                  ? t("mobileOps.team.breakShort")
                  : translateCanonicalRoleLabel(p.label, t) || p.label
              } ${n}${hoursBit}`}
              sx={teamRoleChipSx(
                isBreak ? { kind: "break" } : { roleLabel: p.label },
                { size: "sm" },
              )}
            />
          );
        })}
      </Stack>
      {note ? (
        <Typography sx={{ mt: 0.25, fontSize: "0.65rem", fontWeight: 650, color: OPS_MOBILE.muted }}>
          {note}
        </Typography>
      ) : null}
    </Box>
  );
}

function CompactEmployeeRow({ emp, onOpen, t, locale, mode, dense }) {
  const chip = statusMeta(emp, t);
  const isActive = mode === "working";
  const hours = formatDuration(emp.worked_seconds);
  const breakBit =
    isActive && (emp.on_break || emp.status === "on_break") && emp.open_break_seconds
      ? formatDuration(emp.open_break_seconds)
      : "";
  const onBreak = isActive && (emp.on_break || emp.status === "on_break");
  const assign = emp.assignment || {};
  const roleColorInput = onBreak
    ? { kind: "break" }
    : {
        roleCode: emp.role_code || assign.role_code,
        roleLabel: emp.role_label || assign.role_label,
      };
  const edge = teamRoleEdgeSx(roleColorInput);
  const workType = workTypeDisplay(emp, t);

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
        pl: dense ? 1 : 1.05,
        pr: dense ? 1 : 1.1,
        py: dense ? 0.7 : 0.85,
        borderRadius: 1.75,
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
        bgcolor: alpha("#fff", 0.97),
        ...edge,
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        minHeight: dense ? 56 : 62,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
        <Typography
          sx={{
            fontWeight: 900,
            fontSize: dense ? "0.95rem" : "0.98rem",
            color: OPS_MOBILE.navy,
            lineHeight: 1.2,
            minWidth: 0,
            flex: 1,
          }}
          noWrap
        >
          {emp.display_name}
        </Typography>
        <Typography
          sx={{
            fontWeight: 900,
            fontSize: dense ? "0.9rem" : "0.94rem",
            color: OPS_MOBILE.navy,
            flexShrink: 0,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {hours}
        </Typography>
      </Stack>
      <Stack
        direction="row"
        spacing={0.5}
        alignItems="center"
        sx={{ mt: 0.25, flexWrap: "wrap", rowGap: 0.25, minWidth: 0 }}
      >
        {onBreak ? (
          <RoleTintChip kind="break" t={t} />
        ) : (
          <RoleTintChip
            roleCode={emp.role_code || assign.role_code}
            roleLabel={emp.role_label || assign.role_label}
            t={t}
          />
        )}
        {!onBreak && workType ? (
          <Typography
            sx={{
              fontWeight: 700,
              fontSize: "0.76rem",
              color: OPS_MOBILE.muted,
              lineHeight: 1.25,
              minWidth: 0,
            }}
            noWrap
          >
            {workType}
          </Typography>
        ) : null}
      </Stack>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.3, flexWrap: "wrap" }}>
        {onBreak ? (
          <Typography
            sx={{
              fontSize: "0.76rem",
              fontWeight: 900,
              color: TEAM_ROLE_COLORS.break.text,
              letterSpacing: 0.2,
            }}
          >
            {t("mobileOps.team.onBreak").toUpperCase()}
            {breakBit ? ` · ${breakBit}` : ""}
          </Typography>
        ) : (
          <>
            <Typography sx={{ fontSize: "0.74rem", fontWeight: 700, color: OPS_MOBILE.muted }}>
              {isActive
                ? `${t("mobileOps.team.in")} ${formatTime(emp.clock_in_at, locale)}`
                : `${formatTime(emp.clock_in_at, locale)} – ${formatTime(emp.clock_out_at, locale)}`}
            </Typography>
            <Typography sx={{ fontSize: "0.74rem", fontWeight: 650, color: alpha(OPS_MOBILE.navy, 0.35) }}>
              ·
            </Typography>
            <Typography sx={{ fontSize: "0.74rem", fontWeight: 800, color: chip.color }}>
              {chip.label}
            </Typography>
          </>
        )}
        {onBreak ? (
          <Typography sx={{ fontSize: "0.74rem", fontWeight: 700, color: OPS_MOBILE.muted }}>
            · {t("mobileOps.team.in")} {formatTime(emp.clock_in_at, locale)}
          </Typography>
        ) : null}
      </Stack>
      {!isActive && Array.isArray(emp.role_chips) && emp.role_chips.length ? (
        <Stack direction="row" spacing={0.4} sx={{ mt: 0.4, flexWrap: "wrap", rowGap: 0.35 }}>
          {emp.role_chips.slice(0, 4).map((r) => (
            <RoleTintChip key={r} roleLabel={r} t={t} />
          ))}
        </Stack>
      ) : null}
    </Box>
  );
}

function EmployeeDetailDrawer({
  emp,
  open,
  onClose,
  t,
  locale,
  mobile,
  onViewWeek,
  kind,
}) {
  if (!emp) return null;
  const week = emp.week || {};
  const isWeekEmp = kind === "week";
  const chip =
    isWeekEmp
      ? emp.flag === "ot"
        ? { label: t("mobileOps.team.ot"), color: OPS_MOBILE.danger }
        : emp.flag === "near_40"
          ? { label: t("mobileOps.team.near40"), color: GOLD }
          : { label: t("mobileOps.team.thisWeek"), color: OPS_MOBILE.muted }
      : statusMeta(emp, t);

  return (
    <Drawer
      anchor={mobile ? "bottom" : "right"}
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: mobile ? "100%" : { sm: 420, md: 460 },
          maxHeight: mobile ? "90dvh" : "100%",
          borderTopLeftRadius: mobile ? 16 : 0,
          borderTopRightRadius: mobile ? 16 : 0,
          p: { xs: 1.75, sm: 2 },
          bgcolor: OPS_MOBILE.mist,
        },
      }}
    >
      <Stack spacing={1.25} sx={{ pb: 2.5 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 950, fontSize: "1.2rem", color: OPS_MOBILE.navy }}>
              {emp.display_name}
            </Typography>
            <Typography sx={{ fontWeight: 800, fontSize: "0.85rem", color: chip.color }}>
              {chip.label}
            </Typography>
          </Box>
          <Button onClick={onClose} sx={{ textTransform: "none", fontWeight: 800, minHeight: 40 }}>
            {t("mobileOps.done")}
          </Button>
        </Stack>

        {!isWeekEmp ? (
          <>
            <Typography sx={{ fontWeight: 850, fontSize: "0.82rem", color: GOLD }}>
              {t("mobileOps.team.tab.today")}
            </Typography>
            <Box
              sx={{
                p: 1.15,
                borderRadius: 2,
                bgcolor: alpha("#fff", 0.96),
                border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
              }}
            >
              <DetailRow
                label={t("mobileOps.team.clockIn")}
                value={formatTime(emp.clock_in_at, locale)}
              />
              {emp.clock_out_at ? (
                <DetailRow
                  label={t("mobileOps.team.clockOut")}
                  value={formatTime(emp.clock_out_at, locale)}
                />
              ) : null}
              <DetailRow label={t("mobileOps.team.worked")} value={formatDuration(emp.worked_seconds)} />
              <DetailRow
                label={t("mobileOps.team.breaks")}
                value={formatDuration(emp.break_seconds || 0)}
              />
              {localizeAssignment(emp, t) ? (
                <DetailRow
                  label={
                    emp.status === "working" || emp.status === "on_break"
                      ? t("mobileOps.team.currentRole")
                      : t("mobileOps.team.roles")
                  }
                  value={localizeAssignment(emp, t)}
                />
              ) : null}
              {emp.scheduled_seconds > 0 ? (
                <DetailRow
                  label={t("mobileOps.team.scheduled")}
                  value={formatDuration(emp.scheduled_seconds)}
                />
              ) : null}
            </Box>

            <Typography sx={{ fontWeight: 900, fontSize: "0.88rem", color: OPS_MOBILE.navy }}>
              {t("mobileOps.team.roleTimeline")}
            </Typography>
            <Stack spacing={0.65}>
              {(emp.timeline || [])
                .filter((ev) => ev.type === "role" || ev.type === "break" || ev.type === "gap" || ev.type === "clock_in" || ev.type === "clock_out")
                .map((ev, idx) => {
                  if (ev.type === "clock_in") {
                    return (
                      <Typography key={`ci-${idx}`} sx={{ fontWeight: 800, fontSize: "0.82rem" }}>
                        {formatTime(ev.at, locale)} {t("mobileOps.team.clockedIn")}
                      </Typography>
                    );
                  }
                  if (ev.type === "clock_out") {
                    return (
                      <Typography key={`co-${idx}`} sx={{ fontWeight: 800, fontSize: "0.82rem" }}>
                        {formatTime(ev.at, locale)} {t("mobileOps.team.clockedOut")}
                      </Typography>
                    );
                  }
                  if (ev.type === "gap") {
                    return (
                      <Box
                        key={`gap-${idx}`}
                        sx={{
                          px: 1,
                          py: 0.7,
                          borderRadius: 1.5,
                          bgcolor: alpha(OPS_MOBILE.danger, 0.06),
                          border: `1px dashed ${alpha(OPS_MOBILE.danger, 0.35)}`,
                        }}
                      >
                        <Typography sx={{ fontWeight: 800, fontSize: "0.82rem", color: OPS_MOBILE.danger }}>
                          {formatTime(ev.started_at, locale)}
                          {ev.ended_at
                            ? `–${formatTime(ev.ended_at, locale)}`
                            : `–${t("mobileOps.team.now")}`}{" "}
                          {t("mobileOps.team.dataGap")} {formatDuration(ev.duration_seconds)}
                        </Typography>
                      </Box>
                    );
                  }
                  if (ev.type === "break") {
                    const bc = TEAM_ROLE_COLORS.break;
                    return (
                      <Box
                        key={`br-${idx}`}
                        sx={{
                          px: 1,
                          py: 0.65,
                          borderRadius: 1.5,
                          bgcolor: bc.bg,
                          border: `1px solid ${bc.border}`,
                          borderLeft: `3px solid ${bc.accent}`,
                        }}
                      >
                        <Typography sx={{ fontWeight: 800, fontSize: "0.82rem", color: bc.text }}>
                          {formatTime(ev.started_at, locale)}
                          {ev.ended_at
                            ? `–${formatTime(ev.ended_at, locale)}`
                            : `–${t("mobileOps.team.now")}`}{" "}
                          {t("mobileOps.team.break")} {formatDuration(ev.duration_seconds)}
                        </Typography>
                      </Box>
                    );
                  }
                  const rc = teamRoleColors({
                    roleCode: ev.role_code,
                    roleLabel: ev.role_label || ev.assignment_label,
                  });
                  return (
                    <Box
                      key={`role-${idx}`}
                      sx={{
                        px: 1,
                        py: 0.65,
                        borderRadius: 1.5,
                        bgcolor: alpha("#fff", 0.95),
                        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                        borderLeft: `3px solid ${rc.accent}`,
                      }}
                    >
                      <Stack direction="row" spacing={0.6} alignItems="center" flexWrap="wrap">
                        <Typography sx={{ fontWeight: 800, fontSize: "0.82rem", color: OPS_MOBILE.muted }}>
                          {formatTime(ev.started_at, locale)}
                          {ev.ended_at
                            ? `–${formatTime(ev.ended_at, locale)}`
                            : `–${t("mobileOps.team.now")}`}
                        </Typography>
                        <RoleTintChip
                          roleCode={ev.role_code}
                          roleLabel={ev.role_label}
                          t={t}
                        />
                        {workTypeDisplay(ev, t) ? (
                          <Typography sx={{ fontWeight: 700, fontSize: "0.78rem", color: OPS_MOBILE.muted }}>
                            {workTypeDisplay(ev, t)}
                          </Typography>
                        ) : null}
                        <Typography sx={{ fontWeight: 700, fontSize: "0.78rem", color: OPS_MOBILE.muted }}>
                          {formatDuration(ev.duration_seconds)}
                        </Typography>
                      </Stack>
                    </Box>
                  );
                })}
            </Stack>

            {week.worked_seconds != null ? (
              <Box
                sx={{
                  mt: 0.5,
                  p: 1.15,
                  borderRadius: 2,
                  bgcolor: alpha(GOLD, 0.1),
                  border: `1px solid ${alpha(GOLD, 0.28)}`,
                }}
              >
                <Typography sx={{ fontWeight: 900, fontSize: "0.9rem", color: OPS_MOBILE.navy }}>
                  {t("mobileOps.team.thisWeek")} {formatDuration(week.worked_seconds)}
                </Typography>
                {week.flag === "ot" ? (
                  <Typography sx={{ fontWeight: 800, fontSize: "0.82rem", color: OPS_MOBILE.danger }}>
                    {formatDuration(week.ot_seconds)} {t("mobileOps.team.ot")}
                  </Typography>
                ) : (
                  <Typography sx={{ fontWeight: 750, fontSize: "0.82rem", color: OPS_MOBILE.muted }}>
                    {formatDuration(week.seconds_to_threshold)} {t("mobileOps.team.to40")}
                  </Typography>
                )}
                {onViewWeek ? (
                  <Button
                    onClick={onViewWeek}
                    sx={{
                      mt: 0.5,
                      px: 0,
                      minHeight: 36,
                      textTransform: "none",
                      fontWeight: 850,
                      color: OPS_MOBILE.blue,
                    }}
                  >
                    {t("mobileOps.team.viewWeek")} →
                  </Button>
                ) : null}
              </Box>
            ) : null}
          </>
        ) : (
          <>
            <Box
              sx={{
                p: 1.15,
                borderRadius: 2,
                bgcolor: alpha("#fff", 0.96),
                border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
              }}
            >
              <DetailRow label={t("mobileOps.team.totalWorked")} value={formatDuration(emp.worked_seconds)} />
              <DetailRow
                label={t("mobileOps.team.regular")}
                value={formatDuration(emp.regular_seconds)}
              />
              {emp.ot_seconds > 0 ? (
                <DetailRow label={t("mobileOps.team.ot")} value={formatDuration(emp.ot_seconds)} />
              ) : (
                <DetailRow
                  label={t("mobileOps.team.to40")}
                  value={formatDuration(emp.seconds_to_threshold)}
                />
              )}
              <DetailRow label={t("mobileOps.team.breaks")} value={formatDuration(emp.break_seconds || 0)} />
              {emp.scheduled_hours > 0 ? (
                <DetailRow
                  label={t("mobileOps.team.scheduled")}
                  value={`${Number(emp.scheduled_hours).toFixed(1)}h`}
                />
              ) : null}
            </Box>
            <Typography sx={{ fontWeight: 900, fontSize: "0.88rem" }}>
              {t("mobileOps.team.dailyHours")}
            </Typography>
            <Stack spacing={0.45}>
              {(emp.days || [])
                .filter((d) => (d.worked_seconds || 0) > 0 || (d.scheduled_hours || 0) > 0)
                .map((d) => (
                  <Stack
                    key={d.date_et}
                    direction="row"
                    justifyContent="space-between"
                    sx={{
                      px: 1,
                      py: 0.55,
                      borderRadius: 1.25,
                      bgcolor: alpha("#fff", 0.9),
                      border: `1px solid ${alpha(OPS_MOBILE.navy, 0.06)}`,
                    }}
                  >
                    <Typography sx={{ fontWeight: 750, fontSize: "0.82rem" }}>
                      {formatNavLabel(d.date_et, "____", locale, t).replace(/^Today · /, "")}
                    </Typography>
                    <Typography sx={{ fontWeight: 850, fontSize: "0.82rem" }}>
                      {formatDuration(d.worked_seconds)}
                      {d.scheduled_hours > 0 ? (
                        <Box component="span" sx={{ color: OPS_MOBILE.muted, fontWeight: 700 }}>
                          {" "}
                          / {Number(d.scheduled_hours).toFixed(1)}h
                        </Box>
                      ) : null}
                    </Typography>
                  </Stack>
                ))}
            </Stack>
            {(emp.role_hours || []).length ? (
              <>
                <Typography sx={{ fontWeight: 900, fontSize: "0.88rem" }}>
                  {t("mobileOps.team.roleHours")}
                </Typography>
                <Stack spacing={0.4}>
                  {emp.role_hours.map((r) => (
                    <Stack
                      key={r.label}
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                      spacing={1}
                      sx={{ px: 0.25 }}
                    >
                      <RoleTintChip roleLabel={r.label} t={t} />
                      <Typography sx={{ fontWeight: 850, fontSize: "0.84rem" }}>
                        {formatDuration(r.duration_seconds)}
                      </Typography>
                    </Stack>
                  ))}
                </Stack>
              </>
            ) : null}
          </>
        )}
      </Stack>
    </Drawer>
  );
}

function DetailRow({ label, value }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={1} sx={{ py: 0.25 }}>
      <Typography sx={{ fontWeight: 700, fontSize: "0.84rem", color: OPS_MOBILE.muted }}>{label}</Typography>
      <Typography sx={{ fontWeight: 850, fontSize: "0.84rem", color: OPS_MOBILE.navy, textAlign: "right" }}>
        {value}
      </Typography>
    </Stack>
  );
}

function WeekEmployeeRow({ emp, onOpen, t, dense }) {
  const flag = emp.flag;
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
        px: 1.1,
        py: dense ? 0.7 : 0.85,
        borderRadius: 1.75,
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
        bgcolor: alpha("#fff", 0.97),
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        minHeight: 54,
      }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
        <Typography sx={{ fontWeight: 900, fontSize: "0.96rem", color: OPS_MOBILE.navy }} noWrap>
          {emp.display_name}
        </Typography>
        <Typography sx={{ fontWeight: 950, fontSize: "0.92rem", fontVariantNumeric: "tabular-nums" }}>
          {formatDuration(emp.worked_seconds)}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mt: 0.25, flexWrap: "wrap" }}>
        {flag === "ot" ? (
          <>
            <Typography sx={{ fontSize: "0.76rem", fontWeight: 750, color: OPS_MOBILE.muted }}>
              {formatDuration(emp.regular_seconds)} {t("mobileOps.team.regular")} ·{" "}
              {formatDuration(emp.ot_seconds)} {t("mobileOps.team.ot")}
            </Typography>
            <Chip
              size="small"
              label={t("mobileOps.team.ot")}
              sx={{
                height: 20,
                fontWeight: 850,
                fontSize: "0.68rem",
                bgcolor: alpha(OPS_MOBILE.danger, 0.12),
                color: OPS_MOBILE.danger,
              }}
            />
          </>
        ) : flag === "near_40" ? (
          <>
            <Typography sx={{ fontSize: "0.76rem", fontWeight: 750, color: OPS_MOBILE.muted }}>
              {formatDuration(emp.seconds_to_threshold)} {t("mobileOps.team.to40")}
            </Typography>
            <Chip
              size="small"
              label={t("mobileOps.team.near40")}
              sx={{
                height: 20,
                fontWeight: 850,
                fontSize: "0.68rem",
                bgcolor: alpha(GOLD, 0.16),
                color: GOLD,
              }}
            />
          </>
        ) : (
          <Typography sx={{ fontSize: "0.76rem", fontWeight: 700, color: OPS_MOBILE.muted }}>
            {formatDuration(emp.seconds_to_threshold)} {t("mobileOps.team.to40")}
          </Typography>
        )}
      </Stack>
    </Box>
  );
}

export default function TeamStatusFlow({ onBack, onLock }) {
  const { t, locale } = useI18n();
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const dense = useMediaQuery(theme.breakpoints.up("md"));
  const [tab, setTab] = useState("today");
  const [dateEt, setDateEt] = useState(() => etTodayYmd());
  const [upcomingDate, setUpcomingDate] = useState(() => shiftYmd(etTodayYmd(), 1));
  const [dayData, setDayData] = useState(null);
  const [weekData, setWeekData] = useState(null);
  const [upcomingData, setUpcomingData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [selectedKind, setSelectedKind] = useState("day");

  const todayEt = useMemo(() => etTodayYmd(), []);
  const isToday = dateEt === todayEt;

  const loadToday = useCallback(
    async (day) => {
      setLoading(true);
      setError("");
      try {
        const res = await getTeamStatus(day);
        setDayData(res.data || null);
      } catch (e) {
        setDayData(null);
        setError(e?.response?.data?.error || e?.message || t("mobileOps.team.loadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  const loadWeek = useCallback(
    async (day) => {
      setLoading(true);
      setError("");
      try {
        const res = await getTeamStatusWeek(day);
        setWeekData(res.data || null);
      } catch (e) {
        setWeekData(null);
        setError(e?.response?.data?.error || e?.message || t("mobileOps.team.loadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  const loadUpcoming = useCallback(
    async (day) => {
      setLoading(true);
      setError("");
      try {
        const res = await getTeamStatusUpcoming(day);
        setUpcomingData(res.data || null);
        if (res.data?.date_et) setUpcomingDate(res.data.date_et);
      } catch (e) {
        setUpcomingData(null);
        setError(e?.response?.data?.error || e?.message || t("mobileOps.team.loadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    if (tab === "today") void loadToday(dateEt);
    else if (tab === "week") void loadWeek(dateEt);
    else void loadUpcoming(upcomingDate);
  }, [tab, dateEt, upcomingDate, loadToday, loadWeek, loadUpcoming]);

  const summary = dayData?.summary || {};
  const working = dayData?.working_now || [];
  const worked = dayData?.worked || [];
  const weekSummary = weekData?.summary || {};
  const weekEmployees = weekData?.employees || [];
  const upSummary = upcomingData?.summary || {};
  const upGroups = upcomingData?.groups || [];

  const openDayEmp = (emp) => {
    setSelectedKind("day");
    setSelected(emp);
  };
  const openWeekEmp = (emp) => {
    setSelectedKind("week");
    setSelected({ ...emp, status: emp.flag === "ot" ? "completed" : "completed" });
  };

  return (
    <OpsMobileShell
      maxWidth={tab === "today" && dense ? 960 : 720}
      sx={{ px: { xs: 1.25, sm: 2, md: 2.5 }, py: { xs: 1.15, sm: 1.75 } }}
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

      <TabBar
        tab={tab}
        onChange={(next) => {
          setSelected(null);
          setTab(next);
        }}
        t={t}
      />

      {tab === "today" || tab === "week" ? (
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          spacing={0.5}
          sx={{
            mb: 1,
            px: 0.35,
            py: 0.35,
            borderRadius: 2,
            bgcolor: alpha("#fff", 0.9),
            border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
          }}
        >
          <IconButton
            aria-label={t("mobileOps.team.prevDay")}
            onClick={() => setDateEt((d) => shiftYmd(d, tab === "week" ? -7 : -1))}
            sx={{ minWidth: 44, minHeight: 44 }}
          >
            <ChevronLeftIcon />
          </IconButton>
          <Box sx={{ textAlign: "center", minWidth: 0 }}>
            <Typography sx={{ fontWeight: 900, color: OPS_MOBILE.navy, fontSize: "0.98rem" }}>
              {tab === "week"
                ? formatWeekRange(weekData?.week_start, weekData?.week_end, locale) ||
                  formatNavLabel(dateEt, todayEt, locale, t)
                : formatNavLabel(dateEt, todayEt, locale, t)}
            </Typography>
            {!isToday && tab === "today" ? (
              <Button
                size="small"
                onClick={() => setDateEt(todayEt)}
                sx={{ textTransform: "none", fontWeight: 800, mt: 0.1, minHeight: 32, py: 0 }}
              >
                {t("mobileOps.team.jumpToday")}
              </Button>
            ) : null}
          </Box>
          <IconButton
            aria-label={t("mobileOps.team.nextDay")}
            onClick={() => setDateEt((d) => shiftYmd(d, tab === "week" ? 7 : 1))}
            disabled={tab === "today" ? dateEt >= todayEt : false}
            sx={{ minWidth: 44, minHeight: 44 }}
          >
            <ChevronRightIcon />
          </IconButton>
        </Stack>
      ) : null}

      {error ? (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <Box sx={{ py: 5, display: "grid", placeItems: "center" }}>
          <CircularProgress size={26} />
        </Box>
      ) : null}

      {!loading && tab === "today" ? (
        <>
          <SummaryStrip
            items={
              isToday
                ? [
                    {
                      key: "w",
                      value: summary.working_count ?? 0,
                      label: t("mobileOps.team.working"),
                      color: OPS_MOBILE.success,
                    },
                    {
                      key: "b",
                      value: summary.break_count ?? 0,
                      label: t("mobileOps.team.breakShort"),
                      color: "#b45309",
                    },
                    {
                      key: "d",
                      value: summary.worked_count ?? 0,
                      label: t("mobileOps.team.workedTodayShort"),
                    },
                    {
                      key: "h",
                      value: formatDuration(summary.total_worked_seconds),
                      label: t("mobileOps.team.hoursShort"),
                    },
                  ]
                : [
                    {
                      key: "d",
                      value: summary.worked_count ?? 0,
                      label: t("mobileOps.team.worked"),
                    },
                    {
                      key: "h",
                      value: formatDuration(summary.total_worked_seconds),
                      label: t("mobileOps.team.hoursShort"),
                    },
                  ]
            }
          />

          {isToday ? (
            <RoleCoverageLine
              title={t("mobileOps.team.activeRoles")}
              parts={summary.active_roles || []}
              t={t}
            />
          ) : null}
          <RoleCoverageLine
            title={t("mobileOps.team.workedTodayRoles")}
            parts={summary.worked_today_roles || []}
            note={summary.worked_today_roles_note || t("mobileOps.team.workedTodayRolesNote")}
            t={t}
          />

          {isToday ? (
            <Box sx={{ mb: 1.35 }}>
              <Typography
                sx={{
                  fontWeight: 950,
                  mb: 0.65,
                  color: OPS_MOBILE.navy,
                  fontSize: "0.88rem",
                  letterSpacing: 0.2,
                }}
              >
                {t("mobileOps.team.workingNow")}
              </Typography>
              <Stack spacing={0.65}>
                {!working.length ? (
                  <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 650, fontSize: 13 }}>
                    {t("mobileOps.team.noneWorking")}
                  </Typography>
                ) : (
                  working.map((emp) => (
                    <Box key={`w-${emp.user_id}`}>
                      <Box sx={{ display: { xs: "block", md: "none" } }}>
                        <CompactEmployeeRow
                          emp={emp}
                          onOpen={openDayEmp}
                          t={t}
                          locale={locale}
                          mode="working"
                        />
                      </Box>
                      <DesktopEmpRow
                        emp={emp}
                        onOpen={openDayEmp}
                        t={t}
                        locale={locale}
                        active
                      />
                    </Box>
                  ))
                )}
              </Stack>
            </Box>
          ) : null}

          <Box sx={{ mb: 1.5 }}>
            <Typography
              sx={{
                fontWeight: 950,
                mb: 0.65,
                color: OPS_MOBILE.navy,
                fontSize: "0.88rem",
              }}
            >
              {isToday ? t("mobileOps.team.workedToday") : t("mobileOps.team.worked")}
            </Typography>
            <Stack spacing={0.65}>
              {!worked.length ? (
                <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 650, fontSize: 13 }}>
                  {t("mobileOps.team.noneWorked")}
                </Typography>
              ) : (
                worked.map((emp) => (
                  <Box key={`d-${emp.user_id}`}>
                    <Box sx={{ display: { xs: "block", md: "none" } }}>
                      <CompactEmployeeRow
                        emp={emp}
                        onOpen={openDayEmp}
                        t={t}
                        locale={locale}
                        mode="worked"
                      />
                    </Box>
                    <DesktopEmpRow
                      emp={emp}
                      onOpen={openDayEmp}
                      t={t}
                      locale={locale}
                      active={false}
                    />
                  </Box>
                ))
              )}
            </Stack>
          </Box>

          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </>
      ) : null}

      {!loading && tab === "week" ? (
        <>
          <SummaryStrip
            items={[
              {
                key: "t",
                value: formatDuration(weekSummary.total_worked_seconds),
                label: t("mobileOps.team.totalShort"),
              },
              {
                key: "n",
                value: weekSummary.near_count ?? 0,
                label: t("mobileOps.team.near40"),
                color: GOLD,
              },
              {
                key: "o",
                value: weekSummary.ot_count ?? 0,
                label: t("mobileOps.team.ot"),
                color: OPS_MOBILE.danger,
              },
            ]}
          />
          <Stack spacing={0.65} sx={{ mb: 1.5 }}>
            {!weekEmployees.length ? (
              <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 650, fontSize: 13 }}>
                {t("mobileOps.team.noneWeek")}
              </Typography>
            ) : (
              weekEmployees.map((emp) => (
                <WeekEmployeeRow key={emp.user_id} emp={emp} onOpen={openWeekEmp} t={t} dense={dense} />
              ))
            )}
          </Stack>
          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </>
      ) : null}

      {!loading && tab === "upcoming" ? (
        <>
          <Stack
            direction="row"
            spacing={0.5}
            sx={{
              mb: 1,
              overflowX: "auto",
              pb: 0.25,
              mx: -0.25,
              px: 0.25,
              WebkitOverflowScrolling: "touch",
            }}
          >
            {(upcomingData?.chips || []).map((chip) => {
              const active = chip.date_et === upcomingDate;
              return (
                <Button
                  key={chip.date_et}
                  onClick={() => setUpcomingDate(chip.date_et)}
                  sx={{
                    minWidth: 64,
                    minHeight: 40,
                    px: 1,
                    flexShrink: 0,
                    textTransform: "none",
                    fontWeight: 850,
                    fontSize: "0.78rem",
                    borderRadius: 1.5,
                    color: active ? OPS_MOBILE.navy : OPS_MOBILE.muted,
                    bgcolor: active ? alpha(GOLD, 0.2) : alpha("#fff", 0.9),
                    border: `1px solid ${active ? alpha(GOLD, 0.5) : alpha(OPS_MOBILE.navy, 0.08)}`,
                  }}
                >
                  {chip.is_tomorrow ? t("mobileOps.team.tomorrowShort") : chip.label}
                </Button>
              );
            })}
          </Stack>

          <SummaryStrip
            items={[
              {
                key: "s",
                value: upSummary.staff_count ?? 0,
                label: t("mobileOps.team.staff"),
              },
              {
                key: "h",
                value: `${Number(upSummary.scheduled_hours || 0).toFixed(1)}h`,
                label: t("mobileOps.team.scheduledHrs"),
              },
            ]}
          />

          <Typography sx={{ fontWeight: 950, mb: 0.75, fontSize: "0.9rem", color: OPS_MOBILE.navy }}>
            {upcomingData?.is_tomorrow
              ? t("mobileOps.team.tomorrow")
              : upcomingData?.day_label || upcomingDate}
          </Typography>

          <Stack spacing={1.1} sx={{ mb: 1.5 }}>
            {!upGroups.length ? (
              <Typography sx={{ color: OPS_MOBILE.muted, fontWeight: 650, fontSize: 13 }}>
                {t("mobileOps.team.noneUpcoming")}
              </Typography>
            ) : (
              upGroups.map((g) => (
                <Box key={g.start_time || "x"}>
                  <Typography
                    sx={{
                      fontWeight: 900,
                      fontSize: "0.8rem",
                      color: GOLD,
                      mb: 0.45,
                      letterSpacing: 0.3,
                    }}
                  >
                    {formatHhMm(g.start_time, locale)}
                  </Typography>
                  <Stack spacing={0.55}>
                    {(g.entries || []).map((row) => {
                      const plannedRoleLabel = (() => {
                        const fromRoles = Array.isArray(row.roles) ? row.roles[0] : null;
                        const key = resolveTeamRoleColorKey({
                          roleLabel: row.role_label || fromRoles || row.assignment_label,
                          label: fromRoles,
                        });
                        if (key === "wash_dry") return "Wash-Dry";
                        if (key === "sort") return "Sort";
                        if (key === "fold") return "Fold";
                        return row.role_label || null;
                      })();
                      return (
                      <Box
                        key={`${row.user_id}-${row.start_time}-${row.end_time}`}
                        sx={{
                          px: 1.1,
                          py: 0.75,
                          borderRadius: 1.75,
                          bgcolor: alpha("#fff", 0.97),
                          border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
                          ...(plannedRoleLabel
                            ? teamRoleEdgeSx({ roleLabel: plannedRoleLabel })
                            : null),
                        }}
                      >
                        <Stack direction="row" justifyContent="space-between" alignItems="baseline">
                          <Typography sx={{ fontWeight: 900, fontSize: "0.94rem", color: OPS_MOBILE.navy }}>
                            {row.display_name}
                          </Typography>
                          <Typography
                            sx={{
                              fontWeight: 850,
                              fontSize: "0.82rem",
                              color: OPS_MOBILE.muted,
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {Number(row.hours || 0).toFixed(0)}h
                          </Typography>
                        </Stack>
                        <Typography sx={{ fontSize: "0.76rem", fontWeight: 700, color: OPS_MOBILE.muted }}>
                          {formatHhMm(row.start_time, locale)}–{formatHhMm(row.end_time, locale)}
                        </Typography>
                        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.25, flexWrap: "wrap" }}>
                          {plannedRoleLabel ? (
                            <RoleTintChip roleLabel={plannedRoleLabel} t={t} />
                          ) : null}
                          {row.work_type_label ? (
                            <Typography sx={{ fontSize: "0.76rem", fontWeight: 700, color: OPS_MOBILE.muted }}>
                              {translateCanonicalWorkLabel(row.work_type_label, t) || row.work_type_label}
                            </Typography>
                          ) : null}
                        </Stack>
                      </Box>
                      );
                    })}
                  </Stack>
                </Box>
              ))
            )}
          </Stack>
          <OpsLockButton onClick={onLock} fullWidth label={t("mobileOps.lock")} />
        </>
      ) : null}

      <EmployeeDetailDrawer
        emp={selected}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        t={t}
        locale={locale}
        mobile={mobile}
        kind={selectedKind}
        onViewWeek={
          selectedKind === "day"
            ? () => {
                setSelected(null);
                setTab("week");
              }
            : undefined
        }
      />
    </OpsMobileShell>
  );
}

function DesktopEmpRow({ emp, onOpen, t, locale, active }) {
  const chip = statusMeta(emp, t);
  const onBreak = active && (emp.on_break || emp.status === "on_break");
  const assign = emp.assignment || {};
  const edge = teamRoleEdgeSx(
    onBreak
      ? { kind: "break" }
      : { roleCode: emp.role_code || assign.role_code, roleLabel: emp.role_label || assign.role_label },
  );
  return (
    <Box
      component="button"
      type="button"
      onClick={() => onOpen(emp)}
      sx={{
        display: { xs: "none", md: "grid" },
        gridTemplateColumns: "1.4fr 0.7fr 1.6fr 0.8fr 0.7fr",
        gap: 0.5,
        alignItems: "center",
        width: "100%",
        m: 0,
        px: 1.1,
        py: 0.7,
        textAlign: "left",
        borderRadius: 1.5,
        border: `1px solid ${alpha(OPS_MOBILE.navy, 0.08)}`,
        bgcolor: alpha("#fff", 0.97),
        ...edge,
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        minHeight: 48,
      }}
    >
      <Typography sx={{ fontWeight: 900, fontSize: "0.9rem", color: OPS_MOBILE.navy }} noWrap>
        {emp.display_name}
      </Typography>
      <Typography sx={{ fontWeight: 800, fontSize: "0.78rem", color: chip.color }}>{chip.label}</Typography>
      <Stack direction="row" spacing={0.45} alignItems="center" sx={{ minWidth: 0, flexWrap: "wrap" }}>
        {onBreak ? (
          <RoleTintChip kind="break" t={t} />
        ) : emp.role_label || assign.role_label || emp.role_code ? (
          <RoleTintChip
            roleCode={emp.role_code || assign.role_code}
            roleLabel={emp.role_label || assign.role_label}
            t={t}
          />
        ) : (emp.role_chips || []).length ? (
          (emp.role_chips || []).slice(0, 3).map((r) => <RoleTintChip key={r} roleLabel={r} t={t} />)
        ) : (
          <Typography sx={{ fontWeight: 750, fontSize: "0.8rem", color: OPS_MOBILE.muted }}>—</Typography>
        )}
        {!onBreak && workTypeDisplay(emp, t) ? (
          <Typography sx={{ fontWeight: 700, fontSize: "0.76rem", color: OPS_MOBILE.muted }} noWrap>
            {workTypeDisplay(emp, t)}
          </Typography>
        ) : null}
      </Stack>
      <Typography sx={{ fontWeight: 700, fontSize: "0.78rem", color: OPS_MOBILE.muted }}>
        {active
          ? formatTime(emp.clock_in_at, locale)
          : `${formatTime(emp.clock_in_at, locale)}–${formatTime(emp.clock_out_at, locale)}`}
      </Typography>
      <Typography
        sx={{
          fontWeight: 900,
          fontSize: "0.88rem",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {formatDuration(emp.worked_seconds)}
      </Typography>
    </Box>
  );
}
