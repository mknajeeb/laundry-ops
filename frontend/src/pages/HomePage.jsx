import { useEffect, useMemo, useState } from "react";
import { Box, Button, Paper, Stack, Typography } from "@mui/material";
import {
  AccessTime,
  BuildCircle,
  CloudUpload,
  Inventory2,
  LocalShipping,
  PrecisionManufacturing,
  Checklist,
  PointOfSale,
} from "@mui/icons-material";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { TENANT_NAV_ITEMS, tenantNavItemVisible } from "../constants/tenantNav";
import { getTaSessionCurrent } from "../api";
import { useI18n } from "../i18n/I18nContext";

const SECTION_CARD = {
  borderRadius: 3,
  p: 2,
  border: "1px solid #e5e7eb",
  boxShadow: "none",
};

/** Same gate as the Clock nav tile (`ta.clock`, `clock.view`, or portal roles). */
const CLOCK_NAV_ITEM = TENANT_NAV_ITEMS.find((i) => i.to === "/clock");

const TILE_BASE = {
  borderRadius: 2.5,
  textTransform: "none",
  justifyContent: "flex-start",
  py: 1.5,
  px: 1.5,
  fontWeight: 500,
  fontSize: 16,
};

function HomePage({ user }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { t } = useI18n();
  const { user: taUser, hasPerm, loading: authLoading } = useAuth();
  const [clockLoaded, setClockLoaded] = useState(false);
  const [isClockedIn, setIsClockedIn] = useState(false);

  const canSeeClock = useMemo(() => {
    if (!user || !CLOCK_NAV_ITEM) return false;
    return tenantNavItemVisible(user, CLOCK_NAV_ITEM, true, hasPerm);
  }, [user, hasPerm]);

  const displayName = useMemo(() => {
    if (taUser?.first_name || taUser?.last_name) {
      const s = [taUser.first_name, taUser.last_name].filter(Boolean).join(" ").trim();
      if (s) return s;
    }
    if (user?.first_name || user?.last_name) {
      const s = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
      if (s) return s;
    }
    const label =
      taUser?.display_name ||
      user?.display_name ||
      user?.username ||
      taUser?.email ||
      user?.email;
    if (label && String(label).trim()) return String(label).trim();
    return t("home.displayFallback");
  }, [
    taUser?.first_name,
    taUser?.last_name,
    taUser?.display_name,
    taUser?.email,
    user?.first_name,
    user?.last_name,
    user?.display_name,
    user?.username,
    user?.email,
    t,
  ]);

  useEffect(() => {
    if (authLoading || !canSeeClock) {
      setClockLoaded(false);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const res = await getTaSessionCurrent({});
        if (!cancelled) {
          setIsClockedIn(!!res.data?.session);
          setClockLoaded(true);
        }
      } catch {
        if (!cancelled) {
          setIsClockedIn(false);
          setClockLoaded(true);
        }
      }
    };
    load();
    const id = setInterval(load, 60000);
    const onVis = () => {
      if (document.visibilityState === "visible") load();
    };
    const onSessionChanged = () => load();
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("washpro-session-changed", onSessionChanged);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("washpro-session-changed", onSessionChanged);
    };
  }, [authLoading, canSeeClock, pathname]);

  const can = (path) => {
    const item = TENANT_NAV_ITEMS.find((i) => i.to === path);
    if (!item || !user) return false;
    return tenantNavItemVisible(user, item, true, hasPerm);
  };

  const rinseTiles = [
    {
      path: "/dashboard",
      label: "Dashboard",
      icon: <LocalShipping />,
      sx: { ...TILE_BASE, bgcolor: "#0097b2", color: "#ffffff", "&:hover": { bgcolor: "#007f95" } },
    },
    {
      path: "/upload",
      label: "Upload Orders",
      icon: <CloudUpload />,
      sx: {
        ...TILE_BASE,
        bgcolor: "#111827",
        color: "#ffbd59",
        border: "1px solid #ffbd59",
        "&:hover": { bgcolor: "#0b1220" },
      },
    },
    {
      path: "/orders",
      label: "Orders",
      icon: <Inventory2 />,
      sx: {
        ...TILE_BASE,
        bgcolor: "#f8fafc",
        color: "#111827",
        border: "1px solid #e5e7eb",
        "&:hover": { bgcolor: "#f1f5f9" },
      },
    },
    {
      path: "/inventory",
      label: "Inventory",
      icon: <Checklist />,
      sx: {
        ...TILE_BASE,
        bgcolor: "#f8fafc",
        color: "#111827",
        border: "1px solid #e5e7eb",
        "&:hover": { bgcolor: "#f1f5f9" },
      },
    },
    {
      path: "/checkout",
      label: "Checkout",
      icon: <PointOfSale />,
      sx: {
        ...TILE_BASE,
        bgcolor: "#b91c1c",
        color: "#ffffff",
        "&:hover": { bgcolor: "#991b1b" },
      },
    },
  ];

  const employeeTiles = [
    {
      path: "/clock",
      label: "Clock In / Clock Out",
      icon: <AccessTime />,
      sx: { ...TILE_BASE, bgcolor: "#0f766e", color: "#ffffff", "&:hover": { bgcolor: "#0d5f59" } },
    },
    {
      path: "/production",
      label: "Production",
      icon: <PrecisionManufacturing />,
      sx: {
        ...TILE_BASE,
        bgcolor: "#f8fafc",
        color: "#111827",
        border: "1px solid #e5e7eb",
        "&:hover": { bgcolor: "#f1f5f9" },
      },
    },
    {
      path: "/maintenance",
      label: "Maintenance",
      icon: <BuildCircle />,
      sx: {
        ...TILE_BASE,
        bgcolor: "#f8fafc",
        color: "#111827",
        border: "1px solid #e5e7eb",
        "&:hover": { bgcolor: "#f1f5f9" },
      },
    },
  ];

  const visibleRinse = rinseTiles.filter((t) => can(t.path));
  const visibleEmployee = employeeTiles.filter((t) => can(t.path));

  return (
    <Box sx={{ minHeight: "100%", bgcolor: "#ffffff", p: { xs: 1.2, sm: 2 } }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="flex-start"
        spacing={2}
        sx={{ mb: 1.5 }}
      >
        <Stack spacing={1.2} sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontSize: { xs: 26, sm: 32 }, fontWeight: 500, lineHeight: 1.05 }}>
            Laundry Ops
          </Typography>
          <Typography sx={{ color: "#6b7280", fontWeight: 500 }}>
            Choose a module to continue.
          </Typography>
        </Stack>
        <Stack
          alignItems="flex-end"
          spacing={0.25}
          sx={{ flexShrink: 0, maxWidth: "48%", minWidth: 0 }}
        >
          <Typography
            noWrap
            title={displayName}
            sx={{
              fontWeight: 600,
              fontSize: 15,
              lineHeight: 1.2,
              textAlign: "right",
              maxWidth: "100%",
            }}
          >
            {displayName}
          </Typography>
          {canSeeClock && clockLoaded ? (
            <Typography
              sx={{
                fontSize: 12,
                fontWeight: 600,
                color: (theme) =>
                  isClockedIn ? theme.palette.primary.main : theme.palette.text.secondary,
              }}
            >
              {isClockedIn ? t("home.workStatusIn") : t("home.workStatusOut")}
            </Typography>
          ) : null}
        </Stack>
      </Stack>

      <Stack spacing={1.2}>
        {visibleRinse.length > 0 ? (
          <Paper sx={SECTION_CARD}>
            <Typography sx={{ mb: 1, fontWeight: 500, fontSize: 14, letterSpacing: 0.3 }}>
              RINSE FLOW
            </Typography>
            <Stack spacing={1}>
              {visibleRinse.map((t) => (
                <Button
                  key={t.path}
                  fullWidth
                  startIcon={t.icon}
                  sx={t.sx}
                  onClick={() => navigate(t.path)}
                >
                  {t.label}
                </Button>
              ))}
            </Stack>
          </Paper>
        ) : null}

        {visibleEmployee.length > 0 ? (
          <Paper sx={SECTION_CARD}>
            <Typography sx={{ mb: 1, fontWeight: 500, fontSize: 14, letterSpacing: 0.3 }}>
              EMPLOYEE FLOW
            </Typography>
            <Stack spacing={1}>
              {visibleEmployee.map((t) => (
                <Button
                  key={t.path}
                  fullWidth
                  startIcon={t.icon}
                  sx={t.sx}
                  onClick={() => navigate(t.path)}
                >
                  {t.label}
                </Button>
              ))}
            </Stack>
          </Paper>
        ) : null}

        {visibleRinse.length === 0 && visibleEmployee.length === 0 ? (
          <Typography sx={{ color: "#6b7280" }}>No modules are available for your account.</Typography>
        ) : null}
      </Stack>
    </Box>
  );
}

export default HomePage;
