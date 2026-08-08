import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  AppBar,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Snackbar,
  Toolbar,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { ArrowBack, Lock, Logout, Menu, Refresh } from "@mui/icons-material";
import TenantLogo from "./components/TenantLogo";
import ClockInGate from "./components/ClockInGate";
import MobileTenantDrawer from "./components/MobileTenantDrawer";
import TenantNavAccessBoundary from "./components/TenantNavAccessBoundary";
import Sidebar from "./components/Sidebar";
import PlatformSidebar from "./components/PlatformSidebar";
import { useI18n } from "./i18n/I18nContext";
import { hasPlatformAdminRole, isPayrollManagementOnlyUser, isPlatformOnlyUser, isRinseScheduleOnlyUser, tenantDefaultRoute, userMayUseKioskLock, userSatisfiesRoleGate } from "./utils/platformAccess";

import ProductionPage from "./pages/ProductionPage";
import ScoreboardPage from "./pages/ScoreboardPage";
import RinseFoldingDashboardPage from "./pages/RinseFoldingDashboardPage";
import ShiftMonitorPage from "./pages/ShiftMonitorPage";
import DailyShiftRosterPage from "./pages/DailyShiftRosterPage";
import ScanChronologyPage from "./pages/ScanChronologyPage";
import OperationsTimelinePage from "./pages/OperationsTimelinePage";
import ShiftCapacityPlannerPage from "./pages/ShiftCapacityPlannerPage";
import WeeklySchedulePage from "./pages/WeeklySchedulePage";
import WeeklyScheduleEmployeeViewPage from "./pages/WeeklyScheduleEmployeeViewPage";
import PerformanceSettingsPage from "./pages/PerformanceSettingsPage";
import PerformanceUserMappingPage from "./pages/PerformanceUserMappingPage";
import PerformanceBackfillPage from "./pages/PerformanceBackfillPage";
import RinseFoldingTvPage from "./pages/RinseFoldingTvPage";
import MaintenancePage from "./pages/MaintenancePage";
import SupplyUsagePage from "./pages/SupplyUsagePage";
import MachineConfigurationPage from "./pages/MachineConfigurationPage";
import RinseBagLookupPage from "./pages/RinseBagLookupPage";
import RinseOrderSearchPage from "./pages/RinseOrderSearchPage";
import RinseScheduledSyncPage from "./pages/RinseScheduledSyncPage";
import IssuePage from "./pages/IssuePage";
import PeoplePage from "./pages/PeoplePage";
import ClockPage from "./pages/ClockPage";
import CheckoutPage from "./pages/CheckoutPage";
import CheckoutHistoryPage from "./pages/CheckoutHistoryPage";
import Dashboard from "./pages/Dashboard";
import UploadPage from "./pages/UploadPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import KioskUnlockPage from "./pages/KioskUnlockPage";
import AttendancePinPage from "./pages/AttendancePinPage";
import AttendanceRoleSwitchPage from "./pages/AttendanceRoleSwitchPage";
import MaintenanceTaskListPinPage from "./pages/MaintenanceTaskListPinPage";
import EmployeePinHubPage from "./pages/EmployeePinHubPage";
import MaintenanceTaskListReportsPage from "./pages/MaintenanceTaskListReportsPage";
import MaintenanceTaskSettingsPage from "./pages/MaintenanceTaskSettingsPage";
import PartnerRosterPage from "./pages/PartnerRosterPage";
import InventoryPage from "./pages/InventoryPage";
import DiscrepanciesPage from "./pages/DiscrepanciesPage";
import PayrollManagementPage from "./pages/PayrollManagementPage";
import PermissionsPage from "./pages/PermissionsPage";
import NotificationsPage from "./pages/NotificationsPage";
import OrganizationSettingsPage from "./pages/OrganizationSettingsPage";
import DailyRevenueCostPage from "./pages/DailyRevenueCostPage";
import RevenueCostFloorPage from "./pages/RevenueCostFloorPage";
import DailyOperationsPage from "./pages/DailyOperationsPage";
import OrganizationsPlatformPage from "./pages/OrganizationsPlatformPage";
import PlatformAdminPage from "./pages/PlatformAdminPage";
import UserProfilePage from "./pages/UserProfilePage";
import PayrollFormsHubPage from "./pages/PayrollFormsHubPage";
import DocumentsEvidencePage from "./pages/DocumentsEvidencePage";
import {
  authLogout,
  authMe,
  clearAuthSession,
  getClockPayrollUiSettings,
  getCurrentUploadBatch,
  getSavedUser,
} from "./api";
import { useAuth } from "./context/AuthContext";
import { formatSystemDateLong } from "./utils/formatDateLocal";
import { applyAppIconFromOrganizationLogo } from "./utils/appIcon";
import { lockSessionToKiosk } from "./utils/kioskLockNavigation";
import {
  clearPinHubAppSession,
  isPinHubAppSessionActive,
  loadPinHubAppSession,
  pinHubMenuPath,
} from "./utils/pinHubSession";

function MobileTopBar({ pathname, user, onOpenNav, onLogout, showKioskLock, onKioskLock }) {
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();
  const canGoBack = pathname !== "/";
  return (
    <AppBar
      position="static"
      elevation={0}
      sx={{
        flexShrink: 0,
        pt: "env(safe-area-inset-top, 0px)",
        background: "#ffffff",
        color: "#0f172a",
        borderBottom: "1px solid #e2e8f0",
      }}
    >
      <Toolbar sx={{ minHeight: "50px !important", px: 1 }}>
        <IconButton size="small" onClick={onOpenNav} aria-label="Menu" sx={{ mr: 0.5 }}>
          <Menu sx={{ fontSize: 22 }} />
        </IconButton>
        {canGoBack ? (
          <IconButton size="small" onClick={() => navigate(-1)} sx={{ mr: 1 }}><ArrowBack sx={{ fontSize: 18 }} /></IconButton>
        ) : <Box sx={{ width: 8 }} />}
        <Box
          sx={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-start",
            minHeight: 28,
            overflow: "hidden",
          }}
        >
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0, flex: 1 }}>
            <TenantLogo logoUrl={user?.organization_logo_url} size={28} />
            <Typography component="span" noWrap sx={{ fontSize: 18, fontWeight: 700 }}>
              {user?.organization_name || t("common.appName")}
            </Typography>
          </Box>
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, mr: 0.5 }}>
          {showKioskLock ? (
            <IconButton size="small" onClick={onKioskLock} aria-label={t("nav.lockTablet")} sx={{ mr: 0.25 }}>
              <Lock sx={{ fontSize: 18 }} />
            </IconButton>
          ) : null}
          <Button size="small" variant={locale === "en" ? "contained" : "text"} onClick={() => setLocale("en")} sx={{ minWidth: 40 }}>EN</Button>
          <Button size="small" variant={locale === "es" ? "contained" : "text"} onClick={() => setLocale("es")} sx={{ minWidth: 40 }}>ES</Button>
        </Box>
        <IconButton size="small" onClick={onLogout} aria-label={t("nav.logout")} sx={{ mr: 0.25 }}>
          <Logout sx={{ fontSize: 18 }} />
        </IconButton>
        <IconButton size="small" onClick={() => window.location.reload()} aria-label={t("common.refresh")}><Refresh sx={{ fontSize: 18 }} /></IconButton>
      </Toolbar>
    </AppBar>
  );
}

/** Read-only partner roster: /roster/:token (no app session). */
function isPartnerRosterRoute(path) {
  const p = path || "";
  return p.startsWith("/roster/");
}

/** Collapse accidental //path (e.g. …net//pin/veewash) so public PIN routes match. */
function normalizePathname(path) {
  const raw = String(path || "");
  if (!raw) return "/";
  const collapsed = raw.replace(/\/{2,}/g, "/");
  return collapsed.startsWith("/") ? collapsed : `/${collapsed}`;
}

/** Public login: /login or /login/:orgSlug (tenant-specific bookmark URL). */
function isLoginRoute(path) {
  const p = normalizePathname(path);
  return p === "/login" || p.startsWith("/login/");
}

/** Shared-tablet PIN lock: /kiosk/:orgSlug (no session until PIN succeeds). */
function isKioskRoute(path) {
  const p = normalizePathname(path);
  return p === "/kiosk" || p.startsWith("/kiosk/");
}

/** Phone PIN hub: switch role / checklist / inventory (permission-gated). */
function isPinHubRoute(path) {
  const p = normalizePathname(path);
  return p === "/pin" || p.startsWith("/pin/");
}

function isInventoryRoute(path) {
  const p = normalizePathname(path);
  return p === "/inventory" || p.startsWith("/inventory/");
}

function isRevenueCostFloorRoute(path) {
  const p = normalizePathname(path);
  return p === "/revenue-cost/floor" || p.startsWith("/revenue-cost/");
}

/** @deprecated pin hub employees use /revenue-cost/floor — kept for any stale app sessions */
function isPinHubFinanceRoute(path) {
  return isRevenueCostFloorRoute(path);
}

/** Kiosk clock in/out only: /attendance or /attendance/:orgSlug (no app session). */
function isAttendanceRoute(path) {
  const p = normalizePathname(path);
  return p === "/attendance" || p.startsWith("/attendance/");
}

function isPublicPinSurface(path) {
  return isKioskRoute(path) || isAttendanceRoute(path) || isPinHubRoute(path);
}

/** Same rules as LoginPage — kept in sync for tenant bookmark URLs. */
function sanitizeOrgSlugParam(raw) {
  if (!raw) return "";
  try {
    return decodeURIComponent(String(raw))
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 64);
  } catch {
    return "";
  }
}

/**
 * Opening /login/other-tenant while still logged into another org used to redirect straight to /
 * (because `user` was still set from localStorage). Clear session when slug ≠ current tenant.
 */
function LoginWithOrgSlugRoute({ user, setUser }) {
  const { orgSlug: orgSlugParam } = useParams();
  const slug = useMemo(() => sanitizeOrgSlugParam(orgSlugParam), [orgSlugParam]);
  const userSlug = String(user?.organization_slug || "").toLowerCase();

  useLayoutEffect(() => {
    if (!user || !slug) return;
    if (userSlug !== slug) {
      try {
        localStorage.removeItem("ta_token");
      } catch {
        /* ignore */
      }
      clearAuthSession();
      setUser(null);
    }
  }, [user, slug, userSlug, setUser]);

  if (!slug) {
    return <Navigate to="/login" replace />;
  }

  if (user) {
    if (userSlug === slug) {
      return <Navigate to={tenantDefaultRoute(user)} replace />;
    }
    return (
      <Box sx={{ flex: 1, minHeight: "36vh", width: "100%", display: "grid", placeItems: "center" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  return <LoginPage onLoggedIn={setUser} />;
}

/** Floor ops screens use StandardScreenHeader only — hide duplicate global bar (menu, locale, refresh). */
function hideOpsMobileTopBar(pathname) {
  const p = pathname || "";
  if (p === "/checkout" || p.startsWith("/checkout/")) return true;
  if (p === "/rinse/folding-tv") return true;
  return false;
}

function hideTenantSidebar(pathname) {
  return (pathname || "") === "/rinse/folding-tv";
}

function GuardedRoute({ user, roles, permissionAnyOf, children }) {
  const { hasPerm, loading: authLoading } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  const roleOk = !roles?.length || userSatisfiesRoleGate(user, roles);
  if (roleOk) return children;
  if (permissionAnyOf?.length) {
    if (authLoading) {
      return (
        <Box sx={{ display: "grid", placeItems: "center", minHeight: "40vh" }}>
          <CircularProgress size={28} />
        </Box>
      );
    }
    if (permissionAnyOf.some((k) => hasPerm(k))) return children;
  }
  return <Navigate to={tenantDefaultRoute(user)} replace />;
}

function TenantOnlyRoute({ user, children }) {
  if (!user) return <Navigate to="/login" replace />;
  if (isPlatformOnlyUser(user)) return <Navigate to="/platform" replace />;
  return children;
}

function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const isMobile = useMediaQuery("(max-width: 900px)");
  const [updateReady, setUpdateReady] = useState(false);
  const [activeBatch, setActiveBatch] = useState(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [payrollNavVisible, setPayrollNavVisible] = useState(true);
  const [clockKiosk, setClockKiosk] = useState({
    sharedDevice: false,
    idleLockEnabled: true,
    idleLockSeconds: 30,
  });
  const [user, setUser] = useState(getSavedUser());
  const [authLoading, setAuthLoading] = useState(true);
  /** Avoid calling GET /auth/me on every client-side navigation (was a major local slowness). */
  const washproSessionSyncedRef = useRef(false);
  const mainScrollRef = useRef(null);

  const pathname = location.pathname || "/";
  const normalizedPathname = normalizePathname(pathname);
  const isWeeklyScheduleRoute =
    normalizedPathname === "/performance/weekly-schedule" ||
    normalizedPathname.startsWith("/performance/weekly-schedule/");

  /** iOS PWA: keep main content in its own scroller; reset on navigation (fixes mid-page load + header overlap). */
  useLayoutEffect(() => {
    const el = mainScrollRef.current;
    if (el) {
      el.scrollTop = 0;
      el.scrollLeft = 0;
    }
    window.scrollTo(0, 0);
  }, [normalizedPathname]);

  /** Accidental //pin/… must become /pin/… (else falls through to /login). */
  useLayoutEffect(() => {
    if (pathname === normalizedPathname) return;
    navigate(`${normalizedPathname}${location.search || ""}${location.hash || ""}`, { replace: true });
  }, [pathname, normalizedPathname, navigate, location.search, location.hash]);

  const doLogout = async () => {
    try { await authLogout(); } catch { /* ignore */ }
    clearAuthSession();
    washproSessionSyncedRef.current = false;
    setUser(null);
  };

  useEffect(() => {
    if (!user) washproSessionSyncedRef.current = false;
  }, [user]);

  /** Kiosk / attendance / pin hub are anonymous: drop stale session once so PIN flows stay stateless. */
  const kioskStripRef = useRef(false);
  useEffect(() => {
    if (!isPublicPinSurface(normalizedPathname)) {
      kioskStripRef.current = false;
      return;
    }
    // Inventory unlock mints a Washpro session on /pin before navigating away — keep it.
    if (isPinHubAppSessionActive()) return;
    if (kioskStripRef.current) return;
    kioskStripRef.current = true;
    clearAuthSession();
    try {
      localStorage.removeItem("ta_token");
    } catch {
      /* ignore */
    }
    setUser(null);
    washproSessionSyncedRef.current = false;
  }, [normalizedPathname]);

  useEffect(() => {
    async function bootstrap() {
      if (isLoginRoute(pathname) || isPublicPinSurface(pathname)) {
        setAuthLoading(false);
        return;
      }
      if (
        isPinHubAppSessionActive() &&
        (isInventoryRoute(pathname) || isPinHubFinanceRoute(pathname)) &&
        user
      ) {
        setAuthLoading(false);
        washproSessionSyncedRef.current = true;
        return;
      }
      if (washproSessionSyncedRef.current) {
        setAuthLoading(false);
        return;
      }
      try {
        setAuthLoading(true);
        const res = await authMe();
        setUser(res.data || null);
        washproSessionSyncedRef.current = true;
      } catch (e) {
        console.error(e);
        clearAuthSession();
        setUser(null);
        washproSessionSyncedRef.current = false;
      } finally {
        setAuthLoading(false);
      }
    }
    bootstrap();
  }, [pathname, user]);

  useEffect(() => {
    const onRefresh = () => {
      authMe()
        .then((r) => {
          setUser(r.data || null);
          washproSessionSyncedRef.current = true;
        })
        .catch(() => {});
    };
    window.addEventListener("washpro-user-refresh", onRefresh);
    return () => window.removeEventListener("washpro-user-refresh", onRefresh);
  }, []);

  useEffect(() => {
    const onUpdateReady = () => setUpdateReady(true);
    window.addEventListener("washpro:update-ready", onUpdateReady);
    return () => window.removeEventListener("washpro:update-ready", onUpdateReady);
  }, []);

  useEffect(() => {
    if (isLoginRoute(pathname) || !user?.id) {
      setActiveBatch(null);
    }
  }, [pathname, user?.id]);

  useEffect(() => {
    if (!user?.id || isPlatformOnlyUser(user)) return undefined;
    let cancelled = false;
    getClockPayrollUiSettings()
      .then((res) => {
        if (cancelled) return;
        const v = res.data?.payroll?.nav_payroll_visible;
        setPayrollNavVisible(v !== false);
        const c = res.data?.clock || {};
        const sec = Number(c.kiosk_idle_lock_seconds);
        setClockKiosk({
          sharedDevice: !!c.shared_device_attendance,
          idleLockEnabled: c.kiosk_idle_lock_enabled !== false,
          idleLockSeconds: Number.isFinite(sec) && sec >= 0 ? sec : 30,
        });
      })
      .catch(() => {
        if (!cancelled) setPayrollNavVisible(true);
      });
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  const kioskRoleExcluded = useMemo(() => !userMayUseKioskLock(user), [user]);

  const showKioskLock =
    !!user?.id &&
    clockKiosk.sharedDevice &&
    !kioskRoleExcluded &&
    !isRinseScheduleOnlyUser(user) &&
    !isPlatformOnlyUser(user) &&
    // Phone /pin menu inventory session must not fall into shared-tablet kiosk lock.
    !isPinHubAppSessionActive();

  const handleKioskLock = useCallback(() => {
    lockSessionToKiosk(user?.organization_slug);
  }, [user?.organization_slug]);

  useEffect(() => {
    applyAppIconFromOrganizationLogo(user?.organization_logo_url ?? null);
  }, [user?.organization_logo_url]);

  const idleTimerRef = useRef(null);
  useEffect(() => {
    const idleOn =
      showKioskLock &&
      clockKiosk.idleLockEnabled &&
      clockKiosk.idleLockSeconds > 0 &&
      !isLoginRoute(pathname) &&
      !isKioskRoute(pathname) &&
      !isPinHubRoute(pathname) &&
      !isAttendanceRoute(pathname);
    if (!idleOn) return undefined;
    const ms = clockKiosk.idleLockSeconds * 1000;
    const arm = () => {
      window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = window.setTimeout(() => {
        lockSessionToKiosk(user?.organization_slug);
      }, ms);
    };
    const events = ["pointerdown", "keydown", "scroll", "touchstart", "click"];
    events.forEach((e) => window.addEventListener(e, arm, { passive: true }));
    arm();
    return () => {
      window.clearTimeout(idleTimerRef.current);
      events.forEach((e) => window.removeEventListener(e, arm));
    };
  }, [
    showKioskLock,
    clockKiosk.idleLockEnabled,
    clockKiosk.idleLockSeconds,
    pathname,
    user?.organization_slug,
  ]);

  const refreshUploadBatchBadge = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await getCurrentUploadBatch();
      setActiveBatch(res?.data || null);
    } catch {
      setActiveBatch(null);
    }
  }, [user?.id]);

  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    let intervalId;
    /** Stagger after auth / TA identity calls so the first paint does fewer parallel DB round-trips. */
    const t = window.setTimeout(() => {
      if (cancelled) return;
      refreshUploadBatchBadge();
      intervalId = window.setInterval(refreshUploadBatchBadge, 120000);
    }, 150);
    const onBatchChanged = () => refreshUploadBatchBadge();
    window.addEventListener("washpro-upload-batch-changed", onBatchChanged);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
      if (intervalId) window.clearInterval(intervalId);
      window.removeEventListener("washpro-upload-batch-changed", onBatchChanged);
    };
  }, [user?.id, refreshUploadBatchBadge]);

  useEffect(() => {
    if (authLoading || isLoginRoute(pathname) || !user) return;
    if (isPlatformOnlyUser(user) && pathname !== "/platform" && !pathname.startsWith("/platform/")) {
      navigate("/platform", { replace: true });
      return;
    }
    if (
      isPayrollManagementOnlyUser(user) &&
      pathname !== "/payroll" &&
      !pathname.startsWith("/payroll/")
    ) {
      navigate("/payroll", { replace: true });
    }
  }, [authLoading, pathname, user, navigate]);

  const shellBackground = useMemo(
    () => "linear-gradient(145deg, #f8fbff 0%, #f2f6ff 45%, #f7fafc 100%)",
    []
  );

  if (
    authLoading &&
    !isLoginRoute(pathname) &&
    !isPublicPinSurface(pathname) &&
    !isPartnerRosterRoute(pathname) &&
    !(
      isPinHubAppSessionActive() &&
      (isInventoryRoute(pathname) || isPinHubFinanceRoute(pathname))
    )
  ) {
    return (
      <Box sx={{ flex: 1, minHeight: 0, width: "100%", display: "grid", placeItems: "center" }}>
        <Typography>Loading...</Typography>
      </Box>
    );
  }

  // …net//pin/… must become /pin/… before <Routes> match (else empty tree → falls to login).
  if (pathname !== normalizedPathname && isPublicPinSurface(normalizedPathname)) {
    return (
      <Navigate
        to={`${normalizedPathname}${location.search || ""}${location.hash || ""}`}
        replace
      />
    );
  }

  /** Full-screen lock screen: never wrap with sidebar / gates / previous user's session. */
  if (isKioskRoute(pathname)) {
    return (
      <Routes>
        <Route path="/kiosk/:orgSlug" element={<KioskUnlockPage onLoggedIn={setUser} />} />
        <Route path="/kiosk" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  /** Phone PIN hub: permission-gated Switch Role / Checklist / Inventory. */
  if (isPinHubRoute(pathname)) {
    return (
      <Routes>
        <Route path="/pin/:orgSlug" element={<EmployeePinHubPage onLoggedIn={setUser} />} />
        <Route path="/pin" element={<EmployeePinHubPage onLoggedIn={setUser} />} />
        <Route path="*" element={<Navigate to="/pin" replace />} />
      </Routes>
    );
  }

  /**
   * Phone PIN menu → Inventory / Revenue & Cost floor: fullscreen feature
   * (no sidebar / idle kiosk lock / ADMIN gate). Mobile PIN Access is the
   * employee permission source; manager Daily Revenue & Cost stays separate.
   */
  if (
    isPinHubAppSessionActive() &&
    (isInventoryRoute(pathname) || isRevenueCostFloorRoute(pathname))
  ) {
    if (authLoading) {
      return (
        <Box sx={{ flex: 1, minHeight: 0, width: "100%", display: "grid", placeItems: "center" }}>
          <Typography>Loading...</Typography>
        </Box>
      );
    }
    if (!user) {
      const slug = loadPinHubAppSession()?.organization_slug || "";
      clearPinHubAppSession();
      return <Navigate to={pinHubMenuPath(slug)} replace />;
    }
    return (
      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          width: "100%",
          overflowY: "auto",
          WebkitOverflowScrolling: "touch",
          background: shellBackground,
        }}
      >
        <Routes>
          <Route
            path="/inventory"
            element={
              <InventoryPage
                user={user}
                onPinHubDone={() => {
                  washproSessionSyncedRef.current = false;
                  setUser(null);
                }}
              />
            }
          />
          <Route
            path="/revenue-cost/floor"
            element={
              <RevenueCostFloorPage
                user={user}
                onPinHubDone={() => {
                  washproSessionSyncedRef.current = false;
                  setUser(null);
                }}
              />
            }
          />
        </Routes>
      </Box>
    );
  }

  /** Kiosk attendance punch: no sidebar, no auth session. */
  if (isAttendanceRoute(pathname)) {
    return (
      <Routes>
        <Route path="/attendance/role/:orgSlug" element={<AttendanceRoleSwitchPage />} />
        <Route path="/attendance/role" element={<AttendanceRoleSwitchPage />} />
        <Route path="/attendance/maintenance/:orgSlug" element={<MaintenanceTaskListPinPage />} />
        <Route path="/attendance/maintenance" element={<MaintenanceTaskListPinPage />} />
        <Route path="/attendance/:orgSlug" element={<AttendancePinPage />} />
        <Route path="/attendance" element={<AttendancePinPage />} />
      </Routes>
    );
  }

  /** Partner roster share link — read-only, no sidebar. */
  if (isPartnerRosterRoute(pathname)) {
    return (
      <Routes>
        <Route path="/roster/:token" element={<PartnerRosterPage />} />
      </Routes>
    );
  }

  if (!user && !isLoginRoute(pathname) && !isPublicPinSurface(pathname) && !isPartnerRosterRoute(pathname)) {
    return <Navigate to="/login" replace />;
  }

  if (user && isPlatformOnlyUser(user) && !isLoginRoute(pathname)) {
    return (
      <Box sx={{ flex: 1, minHeight: 0, width: "100%", display: "flex", background: shellBackground }}>
        {!isMobile && <PlatformSidebar user={user} onLogout={doLogout} />}
        <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {isMobile && (
            <AppBar position="static" elevation={0} sx={{ flexShrink: 0, borderBottom: "1px solid #e2e8f0", bgcolor: "#fff", color: "#1e1b4b" }}>
              <Toolbar sx={{ minHeight: 48 }}>
                <Typography sx={{ flex: 1, fontWeight: 700 }}>Platform</Typography>
                <Button size="small" onClick={doLogout}>Logout</Button>
              </Toolbar>
            </AppBar>
          )}
          <Box
            ref={mainScrollRef}
            className="app-main-scroll"
            sx={{
              p: { xs: 0, md: 1 },
              flex: 1,
              minWidth: 0,
              minHeight: 0,
              overflowY: "auto",
              overflowX: "hidden",
              WebkitOverflowScrolling: "touch",
              overscrollBehaviorY: "contain",
            }}
          >
            <Routes>
              <Route
                path="/platform"
                element={
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <PlatformAdminPage />
                  </GuardedRoute>
                }
              />
              <Route path="/platform/organizations" element={<OrganizationsPlatformPage />} />
              <Route
                path="/platform/users/:userId"
                element={
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <UserProfilePage user={user} />
                  </GuardedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/platform" replace />} />
            </Routes>
          </Box>
        </Box>
        <Snackbar open={updateReady} anchorOrigin={{ vertical: "top", horizontal: "center" }} onClose={() => setUpdateReady(false)}>
          <Alert severity="info" variant="filled" action={<Button color="inherit" size="small" onClick={() => window.location.reload()}>Refresh</Button>}>
            New app update is ready.
          </Alert>
        </Snackbar>
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, minHeight: 0, width: "100%", display: "flex", background: shellBackground }}>
      {!isMobile && user && !hideTenantSidebar(pathname) && (pathname.startsWith("/platform") && hasPlatformAdminRole(user) ? (
        <PlatformSidebar user={user} onLogout={doLogout} showTenantEntry />
      ) : (
        <Sidebar
          activeBatch={activeBatch}
          user={user}
          onLogout={doLogout}
          showKioskLock={showKioskLock}
          onKioskLock={handleKioskLock}
        />
      ))}
      <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {isMobile && user && !hideTenantSidebar(pathname) && (
          <>
            <MobileTenantDrawer
              open={mobileNavOpen}
              onClose={() => setMobileNavOpen(false)}
              user={user}
              payrollNavVisible={payrollNavVisible}
              activeBatch={activeBatch}
              onLogout={doLogout}
            />
            {hideOpsMobileTopBar(pathname) ? (
              <AppBar
                position="static"
                elevation={0}
                sx={{
                  flexShrink: 0,
                  pt: "env(safe-area-inset-top, 0px)",
                  background: "#ffffff",
                  borderBottom: "1px solid #e2e8f0",
                }}
              >
                <Toolbar sx={{ minHeight: "46px !important", px: 0.75, gap: 0.75 }}>
                  <IconButton size="medium" onClick={() => setMobileNavOpen(true)} aria-label="Menu" sx={{ color: "#0f172a" }}>
                    <Menu sx={{ fontSize: 26 }} />
                  </IconButton>
                  {pathname === "/checkout" ? (
                    <>
                      <Typography
                        component="span"
                        sx={{
                          fontWeight: 800,
                          fontSize: "1.02rem",
                          color: "#0f172a",
                          flex: 1,
                          minWidth: 0,
                          lineHeight: 1.2,
                        }}
                      >
                        {t("ops.mobileBarCheckoutTitle")}
                      </Typography>
                      <Typography
                        component="span"
                        sx={{
                          fontSize: 11,
                          fontWeight: 600,
                          color: "#64748b",
                          whiteSpace: "nowrap",
                          flexShrink: 0,
                          lineHeight: 1.2,
                          textAlign: "right",
                          maxWidth: "42%",
                        }}
                      >
                        {formatSystemDateLong()}
                      </Typography>
                    </>
                  ) : (
                    <Box sx={{ flex: 1 }} />
                  )}
                </Toolbar>
              </AppBar>
            ) : (
              <MobileTopBar
                pathname={pathname}
                user={user}
                onOpenNav={() => setMobileNavOpen(true)}
                onLogout={doLogout}
                showKioskLock={showKioskLock}
                onKioskLock={handleKioskLock}
              />
            )}
          </>
        )}
        <Box
          ref={mainScrollRef}
          className={`app-main-scroll${isWeeklyScheduleRoute ? " app-main-scroll--schedule" : ""}`}
          sx={{
            p: { xs: 0, md: 1 },
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            overflowY: isWeeklyScheduleRoute ? "hidden" : "auto",
            overflowX: "hidden",
            WebkitOverflowScrolling: "touch",
            overscrollBehaviorY: "contain",
            pb: { xs: "env(safe-area-inset-bottom, 0px)", md: 1 },
            ...(isWeeklyScheduleRoute
              ? {
                  display: "flex",
                  flexDirection: "column",
                }
              : {}),
          }}
        >
          <ClockInGate user={user}>
          <TenantNavAccessBoundary user={user} payrollNavVisible={payrollNavVisible}>
          <Routes>
            <Route path="/login/:orgSlug" element={<LoginWithOrgSlugRoute user={user} setUser={setUser} />} />
            <Route path="/login" element={user ? <Navigate to={tenantDefaultRoute(user)} replace /> : <LoginPage onLoggedIn={setUser} />} />
            <Route path="/ta-login" element={<Navigate to={tenantDefaultRoute(user)} replace />} />
            <Route path="/time-clock" element={<Navigate to="/clock" replace />} />
            <Route path="/" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><HomePage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/dashboard" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><Dashboard /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/orders/*" element={<Navigate to="/checkout" replace />} />
            <Route path="/checkout" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><CheckoutPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/checkout-history"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user}>
                    <CheckoutHistoryPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/upload"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute
                    user={user}
                    roles={["ADMIN", "OPS", "UPLOAD"]}
                    permissionAnyOf={["upload.view", "upload.create"]}
                  >
                    <UploadPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/rinse/bag-lookup"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <RinseBagLookupPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/rinse/order-search"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <RinseOrderSearchPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/rinse/scheduled-sync"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <RinseScheduledSyncPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/employees" element={<TenantOnlyRoute user={user}><GuardedRoute user={user} roles={["ADMIN"]}><PeoplePage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/documents"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <DocumentsEvidencePage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/employees/:userId/hr"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <PayrollFormsHubPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/employees/:userId"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <UserProfilePage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/clock" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><ClockPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/issues" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><IssuePage /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/production" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><ProductionPage /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/scoreboard" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><ScoreboardPage /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/performance"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <ShiftMonitorPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/daily-roster"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <DailyShiftRosterPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/scan-chronology"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <ScanChronologyPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/sorting-chronology"
              element={<Navigate to="/performance/scan-chronology?stage=sorting" replace />}
            />
            <Route
              path="/performance/operations-timeline"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <OperationsTimelinePage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/shift-capacity-planner"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <ShiftCapacityPlannerPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/weekly-schedule/employee/:userId"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS", "RINSE"]}>
                    <WeeklyScheduleEmployeeViewPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/weekly-schedule"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS", "RINSE"]}>
                    <WeeklySchedulePage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/settings"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <PerformanceSettingsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/user-mapping"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <PerformanceUserMappingPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/performance/backfill"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <PerformanceBackfillPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/rinse/folding-dashboard"
              element={<Navigate to="/performance" replace />}
            />
            <Route
              path="/rinse/folding-exceptions"
              element={<Navigate to="/performance?activity=folding&status=exception" replace />}
            />
            <Route
              path="/rinse/folding-dashboard-legacy"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <RinseFoldingDashboardPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/rinse/folding-tv"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user}>
                    <RinseFoldingTvPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/maintenance" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><MaintenancePage /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/maintenance/task-lists"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS"]}>
                    <MaintenanceTaskListReportsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/maintenance/task-settings"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <MaintenanceTaskSettingsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/maintenance/supply-usage"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user}>
                    <SupplyUsagePage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/maintenance/machine-configuration"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user}>
                    <MachineConfigurationPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/inventory" element={<TenantOnlyRoute user={user}><GuardedRoute user={user}><InventoryPage user={user} /></GuardedRoute></TenantOnlyRoute>} />
            <Route path="/discrepancies" element={<TenantOnlyRoute user={user}><GuardedRoute user={user} roles={["ADMIN", "OPS"]}><DiscrepanciesPage /></GuardedRoute></TenantOnlyRoute>} />
            <Route
              path="/payroll"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute
                    user={user}
                    roles={["ADMIN", "OPS", "FINANCE", "PAYROLL_ADMIN", "ACCOUNTANT", "PAYROLL_ANALYTICS"]}
                    permissionAnyOf={[
                      "users.view",
                      "ta.settings",
                      "users.edit",
                      "payroll.view",
                      "payroll.analytics.view",
                    ]}
                  >
                    <PayrollManagementPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/payroll-monitor" element={<Navigate to="/payroll" replace />} />
            <Route path="/attendance-setup" element={<Navigate to="/payroll" replace />} />
            <Route
              path="/organization"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <OrganizationSettingsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/operations/daily"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN", "OPS", "MANAGER"]}>
                    <DailyOperationsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/finance/daily-revenue-cost"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <DailyRevenueCostPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/notifications"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user}>
                    <NotificationsPage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/platform/organizations"
              element={
                <TenantOnlyRoute user={user}>
                  <OrganizationsPlatformPage />
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/platform"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <PlatformAdminPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/platform/users/:userId"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["SUPER_ADMIN", "PLATFORM_ADMIN"]}>
                    <UserProfilePage user={user} />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route
              path="/permissions"
              element={
                <TenantOnlyRoute user={user}>
                  <GuardedRoute user={user} roles={["ADMIN"]}>
                    <PermissionsPage />
                  </GuardedRoute>
                </TenantOnlyRoute>
              }
            />
            <Route path="/ta-employees" element={<Navigate to="/employees" replace />} />
          </Routes>
          </TenantNavAccessBoundary>
          </ClockInGate>
        </Box>
      </Box>

      <Snackbar open={updateReady} anchorOrigin={{ vertical: "top", horizontal: "center" }} onClose={() => setUpdateReady(false)}>
        <Alert severity="info" variant="filled" action={<Button color="inherit" size="small" onClick={() => window.location.reload()}>Refresh</Button>}>
          New app update is ready.
        </Alert>
      </Snackbar>
    </Box>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", width: "100%" }}>
        <AppShell />
      </Box>
    </BrowserRouter>
  );
}

export default App;
