import axios from "axios";

/* =========================================
   API BASE
========================================= */

const PRODUCTION_API_FALLBACK =
  "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";

function normalizeApiBase(raw) {
  let b = String(raw || "").trim().replace(/\/+$/, "");
  if (!b) return "";
  // HTTPS pages cannot call HTTP APIs (browser blocks as mixed content → "Network Error").
  if (typeof window !== "undefined" && window.location?.protocol === "https:" && b.startsWith("http://")) {
    b = `https://${b.slice(7)}`;
  }
  return b;
}

function resolveApiBase() {
  if (import.meta.env.DEV) return "";
  const fromEnv = import.meta.env.VITE_API_BASE;
  if (fromEnv != null && String(fromEnv).trim() !== "") {
    return normalizeApiBase(fromEnv);
  }
  return PRODUCTION_API_FALLBACK;
}

const API_BASE = resolveApiBase();

/** No trailing slash; empty in dev when Vite proxy is used. */
export function getWashproApiBase() {
  return normalizeApiBase(API_BASE);
}

const AUTH_TOKEN_KEY = "washpro_token";
const AUTH_USER_KEY = "washpro_user";

export const getAuthToken = () => localStorage.getItem(AUTH_TOKEN_KEY) || "";

/** True when any API token exists (Washpro or legacy TA). */
export const hasAuthToken = () =>
  !!(localStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem("ta_token"));
/** Dedupe + TTL: many components call clock-payroll-ui on first paint (Sidebar, gate, clock page). */
let _clockPayrollUiCache = { res: null, at: 0, inflight: null };
const CLOCK_PAYROLL_UI_TTL_MS = 90000;

function invalidateClockPayrollUiSettingsCache() {
  _clockPayrollUiCache = { res: null, at: 0, inflight: null };
}

export const setAuthSession = ({ token, user }) => {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (user) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  invalidateClockPayrollUiSettingsCache();
  window.dispatchEvent(new CustomEvent("washpro-session-changed"));
};
export const clearAuthSession = () => {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
  invalidateClockPayrollUiSettingsCache();
  window.dispatchEvent(new CustomEvent("washpro-session-changed"));
};
export const getSavedUser = () => {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

axios.interceptors.request.use((config) => {
  const url = String(config.url || "");
  /** Public PIN unlock / kiosk punch — never send another user's Bearer token. */
  if (
    url.includes("/auth/attendance-pin-unlock") ||
    url.includes("/api/public/attendance/pin-punch")
  ) {
    return config;
  }
  const isTa = url.includes("/api/ta/");
  config.headers = config.headers || {};
  const ta = localStorage.getItem("ta_token");
  const wp = getAuthToken();
  if (isTa) {
    if (ta) config.headers.Authorization = `Bearer ${ta}`;
    else if (wp) config.headers.Authorization = `Bearer ${wp}`;
  } else {
    if (wp) config.headers.Authorization = `Bearer ${wp}`;
    else if (ta) config.headers.Authorization = `Bearer ${ta}`;
  }
  return config;
});

/* =========================================
   AUTH
========================================= */

/** Avoid infinite "Signing in…" when the API is unreachable or a proxy hangs (no default axios timeout). */
const AUTH_LOGIN_TIMEOUT_MS = 60000;

export const authLogin = (username, password, organization_slug) =>
  axios.post(
    `${API_BASE}/auth/login`,
    {
      username,
      password,
      ...(organization_slug != null && String(organization_slug).trim() !== ""
        ? { organization_slug: String(organization_slug).trim().toLowerCase() }
        : {}),
    },
    { timeout: AUTH_LOGIN_TIMEOUT_MS },
  );

/** Shared tablet lock screen: unlock session with tenant slug + payroll attendance PIN. */
export const authAttendancePinUnlock = (organization_slug, pin) =>
  axios.post(
    `${API_BASE}/auth/attendance-pin-unlock`,
    {
      organization_slug: String(organization_slug || "").trim().toLowerCase(),
      pin: String(pin || "").trim(),
    },
    { timeout: AUTH_LOGIN_TIMEOUT_MS },
  );

/** Not logged in: change password with current password. */
export const postPublicChangePassword = (body) =>
  axios.post(`${API_BASE}/auth/public/change-password`, body);

export const postPasswordResetRequest = (body) =>
  axios.post(`${API_BASE}/auth/password-reset/request`, body);

export const postPasswordResetComplete = (body) =>
  axios.post(`${API_BASE}/auth/password-reset/complete`, body);

export const getNotificationPreferences = () =>
  axios.get(`${API_BASE}/auth/me/notification-preferences`);

export const putNotificationPreferences = (body) =>
  axios.put(`${API_BASE}/auth/me/notification-preferences`, body);

/** ADMIN: notification groups, event routing, manual dispatch */
export const getNotificationGroups = () =>
  axios.get(`${API_BASE}/auth/notifications/groups`);
export const postNotificationGroup = (body) =>
  axios.post(`${API_BASE}/auth/notifications/groups`, body);
export const putNotificationGroup = (groupId, body) =>
  axios.put(`${API_BASE}/auth/notifications/groups/${groupId}`, body);
export const deleteNotificationGroup = (groupId) =>
  axios.delete(`${API_BASE}/auth/notifications/groups/${groupId}`);
export const getNotificationGroupMembers = (groupId) =>
  axios.get(`${API_BASE}/auth/notifications/groups/${groupId}/members`);
export const putNotificationGroupMembers = (groupId, userIds) =>
  axios.put(`${API_BASE}/auth/notifications/groups/${groupId}/members`, { user_ids: userIds });

export const getNotificationEvents = () =>
  axios.get(`${API_BASE}/auth/notifications/events`);
export const postNotificationEvent = (body) =>
  axios.post(`${API_BASE}/auth/notifications/events`, body);
export const putNotificationEvent = (eventId, body) =>
  axios.put(`${API_BASE}/auth/notifications/events/${eventId}`, body);
export const deleteNotificationEvent = (eventId) =>
  axios.delete(`${API_BASE}/auth/notifications/events/${eventId}`);
export const getNotificationEventAudiences = (eventId) =>
  axios.get(`${API_BASE}/auth/notifications/events/${eventId}/audiences`);
export const putNotificationEventAudiences = (eventId, body) =>
  axios.put(`${API_BASE}/auth/notifications/events/${eventId}/audiences`, body);
export const postNotificationDispatch = (body) =>
  axios.post(`${API_BASE}/auth/notifications/dispatch`, body);

/** Single in-flight GET /auth/me (App bootstrap + refresh events can overlap). */
let _authMeInflight = null;
export const authMe = () => {
  if (_authMeInflight) return _authMeInflight;
  _authMeInflight = axios.get(`${API_BASE}/auth/me`).finally(() => {
    _authMeInflight = null;
  });
  return _authMeInflight;
};

export const putAuthPassword = (body) =>
  axios.put(`${API_BASE}/auth/me/password`, body);

export const authLogout = () =>
  axios.post(`${API_BASE}/auth/logout`);

/** Public: branding for login when user enters organization slug */
export const getPublicOrgBranding = (slug) =>
  axios.get(`${API_BASE}/api/public/organization/branding`, {
    params: { slug: String(slug || "").trim().toLowerCase() },
    validateStatus: (status) => status === 200 || status === 404 || status === 400,
  });

/** Public kiosk: users currently clocked in for tenant slug */
export const getPublicActiveClockIns = (slug) =>
  axios.get(`${API_BASE}/api/public/organization/active-clock-ins`, {
    params: { slug: String(slug || "").trim().toLowerCase() },
    validateStatus: (status) => status === 200 || status === 404 || status === 400,
  });

/** Kiosk attendance: clock in/out with PIN only (no session). */
export const ATTENDANCE_PIN_PUNCH_TIMEOUT_MS = 25000;

export const attendancePinPunch = (organization_slug, pin) =>
  axios.post(
    `${API_BASE}/api/public/attendance/pin-punch`,
    {
      organization_slug: String(organization_slug || "").trim().toLowerCase(),
      pin: String(pin || "").trim(),
    },
    {
      timeout: ATTENDANCE_PIN_PUNCH_TIMEOUT_MS,
      /** Handle 401/403/503 in UI instead of throwing before response body is read. */
      validateStatus: (status) => status >= 200 && status < 600,
    },
  );

/** Public: active tenants for /attendance picker */
export const getPublicOrganizationsForAttendance = () =>
  axios.get(`${API_BASE}/api/public/organizations/for-attendance`, {
    validateStatus: (status) => status === 200 || status === 503,
  });

/** ADMIN: current tenant organization row (slug, display_name, logo_url) */
export const getOrganization = () =>
  axios.get(`${API_BASE}/auth/organization`);

export const putOrganization = (body) =>
  axios.put(`${API_BASE}/auth/organization`, body);

export const uploadOrganizationLogo = (file) => {
  const fd = new FormData();
  fd.append("file", file);
  return axios.post(`${API_BASE}/auth/organization/logo`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

/** SUPER_ADMIN / PLATFORM_ADMIN: all tenants */
export const getPlatformOrganizations = () =>
  axios.get(`${API_BASE}/auth/platform/organizations`);

export const createPlatformOrganization = (body) =>
  axios.post(`${API_BASE}/auth/platform/organizations`, body);

export const putPlatformOrganization = (orgId, body) =>
  axios.put(`${API_BASE}/auth/platform/organizations/${orgId}`, body);

export const deletePlatformOrganization = (orgId) =>
  axios.delete(`${API_BASE}/auth/platform/organizations/${orgId}`);

export const uploadPlatformOrganizationLogo = (orgId, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return axios.post(`${API_BASE}/auth/platform/organizations/${orgId}/logo`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const getPlatformEntitlements = (orgId) =>
  axios.get(`${API_BASE}/auth/platform/organizations/${orgId}/entitlements`);

export const putPlatformEntitlements = (orgId, modules) =>
  axios.put(`${API_BASE}/auth/platform/organizations/${orgId}/entitlements`, { modules });

export const getPlatformPermissionMatrix = () =>
  axios.get(`${API_BASE}/auth/platform/permission-matrix`);

export const createPlatformRole = (payload) =>
  axios.post(`${API_BASE}/auth/platform/roles`, payload);

export const deletePlatformRole = (roleId) =>
  axios.delete(`${API_BASE}/auth/platform/roles/${roleId}`);

export const putPlatformRolePermissions = (roleId, permission_keys) =>
  axios.put(`${API_BASE}/auth/platform/roles/${roleId}/permissions`, {
    permission_keys,
  });

export const getRoles = () =>
  axios.get(`${API_BASE}/auth/roles`);

export const getUsers = () =>
  axios.get(`${API_BASE}/auth/users`);

export const createUser = (payload) =>
  axios.post(`${API_BASE}/auth/users`, payload);

export const updateUser = (userId, payload) =>
  axios.put(`${API_BASE}/auth/users/${userId}`, payload);

/** ADMIN: single Laundry Ops user in your organization (includes geofence / entity tag hints). */
export const getAuthUser = (userId) =>
  axios.get(`${API_BASE}/auth/users/${userId}`);

export const deleteUser = (userId) =>
  axios.delete(`${API_BASE}/auth/users/${userId}`);

/** SUPER_ADMIN / PLATFORM_ADMIN: search logins across tenants */
export const searchPlatformUsers = (q) =>
  axios.get(`${API_BASE}/auth/platform/users`, { params: { q: q || "" } });

export const getPlatformUserProfile = (userId) =>
  axios.get(`${API_BASE}/auth/platform/users/${userId}`);

export const putPlatformUserProfile = (userId, body) =>
  axios.put(`${API_BASE}/auth/platform/users/${userId}`, body);

/* =========================================
   DASHBOARD
========================================= */

export const getDashboard = () =>
  axios.get(`${API_BASE}/dashboard`);

export const getOperationsDashboardSummary = (params = {}) =>
  axios.get(`${API_BASE}/rinse/operations-dashboard/summary`, { params, timeout: 30000 });

/* =========================================
   ORDERS
========================================= */

export const lookupOrdersByScan = (body) => axios.post(`${API_BASE}/orders/lookup_scan`, body);

export const getOrders = (options = {}) =>
  axios.get(`${API_BASE}/orders`, {
    params: {
      ...(options.include_all ? { include_all: 1 } : {}),
      ...(options.checkout_batch ? { checkout_batch: 1 } : {}),
    },
  });

export const updateOrder = (id, data) =>
  axios.put(`${API_BASE}/orders/${id}`, data);

export const deleteOrder = (id) =>
  axios.delete(`${API_BASE}/orders/${id}`);

/* =========================================
   CHECKOUT
========================================= */

export const checkoutOrder = (order_id, employee) =>
  axios.post(`${API_BASE}/checkout`, {
    order_id: order_id,
    employee: employee
  });

export const checkoutBulk = (order_ids, employee) =>
  axios.post(`${API_BASE}/checkout_bulk`, {
    order_ids: order_ids,
    employee: employee
  });

export const getCheckoutLog = (dateValue = "") =>
  axios.get(`${API_BASE}/checkout_log`, {
    params: dateValue ? { date: dateValue } : {}
  });

export const getCheckoutBatchSummary = () =>
  axios.get(`${API_BASE}/checkout/batch_summary`, { timeout: 30000 });

export const undoCheckout = (order_id) =>
  axios.post(`${API_BASE}/checkout_undo`, {
    order_id: order_id
  });

/* =========================================
   UPLOAD ORDERS
========================================= */

export const uploadOrders = (formData) =>
  axios.post(`${API_BASE}/upload_orders`, formData, {
    timeout: 60000,
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });

/** Portal-style CSV (Rinse scrape export). Does not use Excel `transform_orders`. */
export const uploadPortalOrdersCsv = (formData) =>
  axios.post(`${API_BASE}/upload_orders_portal_csv`, formData, {
    timeout: 120000,
    headers: { "Content-Type": "multipart/form-data" },
  });

/** Portal + scan-events CSV in one request (required when upload_batch_require_both_csv is on). */
export const uploadRinseDualCsv = (formData) =>
  axios.post(`${API_BASE}/upload_orders_rinse_dual_csv`, formData, {
    timeout: 120000,
    headers: { "Content-Type": "multipart/form-data" },
  });

/** Optional Rinse scan-events CSV (Bag ID + scans only) for an existing draft upload batch. */
export const uploadRinseScanEventsCsv = (batchId, formData) =>
  axios.post(`${API_BASE}/upload_batches/${batchId}/rinse-scan-events`, formData, {
    timeout: 120000,
    headers: { "Content-Type": "multipart/form-data" },
  });

export const getRinseBagDetail = (bagId) =>
  axios.get(`${API_BASE}/rinse/bags/${encodeURIComponent(bagId)}/detail`, { timeout: 30000 });

export const getRinseBagScanEvents = (bagId, params = {}) =>
  axios.get(`${API_BASE}/rinse/bags/${encodeURIComponent(bagId)}/scan-events`, {
    params,
    timeout: 30000,
  });

export const getRinseScheduledScrapeStatus = () =>
  axios.get(`${API_BASE}/rinse/scheduled-scrape/status`, { timeout: 30000 });

export const getRinseScheduledScrapeRuns = (params = {}) =>
  axios.get(`${API_BASE}/rinse/scheduled-scrape/runs`, { params, timeout: 30000 });

export const searchRinseOrders = (params = {}) =>
  axios.get(`${API_BASE}/rinse/order-search`, { params, timeout: 30000 });

export const getRinseOrderArchiveDetail = (bagId) =>
  axios.get(`${API_BASE}/rinse/order-search/${encodeURIComponent(bagId)}`, { timeout: 30000 });

export const postRinseBagRecomputeCompletion = (bagId) =>
  axios.post(`${API_BASE}/rinse/bags/${encodeURIComponent(bagId)}/recompute-completion`, {}, {
    timeout: 30000,
  });

/** Folding performance list (completed bags only). */
export const listFoldingPerformance = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/performance`, { params, timeout: 30000 });

export const listFoldingExceptions = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/exceptions`, { params, timeout: 30000 });

export const searchFoldingExceptions = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/exceptions/search`, { params, timeout: 30000 });

export const getFoldingExceptionRules = () =>
  axios.get(`${API_BASE}/rinse/folding/settings/exception-rules`, { timeout: 15000 });

export const putFoldingExceptionRules = (body) =>
  axios.put(`${API_BASE}/rinse/folding/settings/exception-rules`, body, { timeout: 15000 });

export const dryRunFoldingExceptionRules = () =>
  axios.post(`${API_BASE}/rinse/folding/exception-rules/dry-run`, {}, { timeout: 300000 });

export const applyFoldingExceptionRules = () =>
  axios.post(`${API_BASE}/rinse/folding/exception-rules/apply`, {}, { timeout: 300000 });

export const getFoldingUserSequence = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/user-sequence`, { params, timeout: 60000 });

export const getFoldingUserProductivity = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/user-productivity`, { params, timeout: 60000 });

export const getProcessingProductivity = (params = {}) =>
  axios.get(`${API_BASE}/rinse/processing/productivity`, { params, timeout: 60000 });

export const getProcessingSettings = () =>
  axios.get(`${API_BASE}/rinse/processing/settings`, { timeout: 15000 });

export const putProcessingSettings = (body) =>
  axios.put(`${API_BASE}/rinse/processing/settings`, body, { timeout: 15000 });

export const listFoldingUserMappings = () =>
  axios.get(`${API_BASE}/rinse/folding/user-mappings`, { timeout: 30000 });

export const upsertFoldingUserMapping = (body) =>
  axios.put(`${API_BASE}/rinse/folding/user-mappings`, body, { timeout: 30000 });

export const deleteFoldingUserMapping = (id) =>
  axios.delete(`${API_BASE}/rinse/folding/user-mappings`, { params: { id }, timeout: 30000 });

export const markFoldingExceptionReviewed = (bagId, body = {}) =>
  axios.post(`${API_BASE}/rinse/folding/exceptions/${encodeURIComponent(bagId)}/reviewed`, body, { timeout: 30000 });

export const approveFoldingException = (bagId, body = {}) =>
  axios.post(`${API_BASE}/rinse/folding/exceptions/${encodeURIComponent(bagId)}/approve`, body, { timeout: 30000 });

export const excludeFoldingException = (bagId, body = {}) =>
  axios.post(`${API_BASE}/rinse/folding/exceptions/${encodeURIComponent(bagId)}/exclude`, body, { timeout: 30000 });

export const bulkFoldingExceptionsAction = (body) =>
  axios.post(`${API_BASE}/rinse/folding/exceptions/bulk-action`, body, { timeout: 120000 });

export const overrideFoldingExceptionReview = (bagId, body = {}) =>
  axios.post(`${API_BASE}/rinse/folding/exceptions/${encodeURIComponent(bagId)}/override`, body, { timeout: 30000 });

export const getFoldingPerformanceDetail = (bagId) =>
  axios.get(`${API_BASE}/rinse/folding/performance/${encodeURIComponent(bagId)}`, {
    timeout: 30000,
  });

export const recomputeFoldingPerformance = (body) =>
  axios.post(`${API_BASE}/rinse/folding/recompute`, body, { timeout: 120000 });

export const runCleanerTicketPresenceScrape = (body) =>
  axios.post(`${API_BASE}/api/rinse/cleaner-ticket-presence/scrape`, body, { timeout: 600000 });

export const runRinseBothSyncs = (body = {}) =>
  axios.post(`${API_BASE}/api/rinse/sync/both`, body, { timeout: 60000 });

export const getCleanerTicketPresenceSummary = () =>
  axios.get(`${API_BASE}/api/rinse/cleaner-ticket-presence/summary`, { timeout: 30000 });

export const overrideFoldingPerformance = (bagId, body) =>
  axios.post(`${API_BASE}/rinse/folding/performance/${encodeURIComponent(bagId)}/override`, body, {
    timeout: 30000,
  });

export const applyFoldingScoringOverride = (bagId, body) =>
  axios.post(
    `${API_BASE}/rinse/folding/performance/${encodeURIComponent(bagId)}/scoring-override`,
    body,
    { timeout: 30000 }
  );

export const getFoldingBenchmarks = () =>
  axios.get(`${API_BASE}/rinse/folding/benchmarks`, { timeout: 15000 });

export const updateFoldingBenchmarks = (body) =>
  axios.put(`${API_BASE}/rinse/folding/benchmarks`, body, { timeout: 15000 });

export const getFoldingDailyStats = (params) =>
  axios.get(`${API_BASE}/rinse/folding/stats/daily`, { params, timeout: 30000 });

export const getFoldingWeeklyStats = (params) =>
  axios.get(`${API_BASE}/rinse/folding/stats/weekly`, { params, timeout: 30000 });

export const getFoldingLeaderboard = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/leaderboard`, { params, timeout: 30000 });

export const getFoldingEmployeeAnalysis = (params = {}) =>
  axios.get(`${API_BASE}/rinse/folding/employee-analysis`, { params, timeout: 30000 });

export const getShiftAnalysisSimple = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/simple`, {
    params: { ...params, _t: Date.now() },
    timeout: 120000,
    headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
  });

/** Phase 2 — employee productivity section only (full bag drilldown, single ET day). */
export const getEmployeeProductivityDashboard = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/employee-productivity`, {
    params: { ...params, _t: Date.now() },
    timeout: 120000,
    headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
  });

/** Daily shift roster — end-of-day labor recording. */
export const getDailyShiftRoster = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/daily-roster`, { params, timeout: 30000 });

export const createDailyShiftRosterEntry = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/daily-roster`, body, { timeout: 30000 });

export const updateDailyShiftRosterEntry = (entryId, body) =>
  axios.put(`${API_BASE}/rinse/shift-analysis/daily-roster/${encodeURIComponent(entryId)}`, body, { timeout: 30000 });

export const deleteDailyShiftRosterEntry = (entryId) =>
  axios.delete(`${API_BASE}/rinse/shift-analysis/daily-roster/${encodeURIComponent(entryId)}`, { timeout: 30000 });

export const importDailyShiftRosterFromPayroll = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/daily-roster/import-from-payroll`, body, { timeout: 30000 });

export const refreshDailyShiftRosterFromPayroll = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/daily-roster/refresh-from-payroll`, body, { timeout: 30000 });

export const batchSaveDailyShiftRoster = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/daily-roster/batch-save`, body, { timeout: 60000 });

export const getWeeklySchedule = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/weekly-schedule`, { params, timeout: 30000 });

export const createWeeklyScheduleEntry = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/weekly-schedule`, body, { timeout: 30000 });

export const updateWeeklyScheduleEntry = (entryId, body) =>
  axios.put(`${API_BASE}/rinse/shift-analysis/weekly-schedule/${encodeURIComponent(entryId)}`, body, { timeout: 30000 });

export const deleteWeeklyScheduleEntry = (entryId) =>
  axios.delete(`${API_BASE}/rinse/shift-analysis/weekly-schedule/${encodeURIComponent(entryId)}`, { timeout: 30000 });

export const moveWeeklyScheduleEntry = (entryId, body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/weekly-schedule/${encodeURIComponent(entryId)}/move`, body, { timeout: 30000 });

export const duplicateWeeklyScheduleEntry = (entryId, body = {}) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/weekly-schedule/${encodeURIComponent(entryId)}/duplicate`, body, { timeout: 30000 });

export const setWeeklyScheduleExclusion = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/weekly-schedule/exclusions`, body, { timeout: 30000 });

export const bulkSetWeeklyScheduleEmployer = (body) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/weekly-schedule/bulk-employer`, body, { timeout: 30000 });

export const getWeeklyScheduleDisplaySettings = () =>
  axios.get(`${API_BASE}/rinse/shift-analysis/weekly-schedule/display-settings`, { timeout: 30000 });

export const updateWeeklyScheduleDisplaySettings = (body) =>
  axios.put(`${API_BASE}/rinse/shift-analysis/weekly-schedule/display-settings`, body, { timeout: 30000 });

export const getShiftAnalysisSummary = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/summary`, { params, timeout: 60000 });

export const getShiftAnalysisPending = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/pending`, { params, timeout: 30000 });

export const getShiftAnalysisRecords = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/records`, { params, timeout: 60000 });

export const getSortingChronology = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/sorting-chronology`, { params, timeout: 60000 });

export const getScanChronology = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/scan-chronology`, { params, timeout: 60000 });

export const getOperationsTimeline = (params = {}) =>
  axios.get(`${API_BASE}/rinse/shift-analysis/operations-timeline`, { params, timeout: 60000 });

export const simulateShiftCapacity = (body = {}) =>
  axios.post(`${API_BASE}/rinse/shift-analysis/shift-capacity-planner/simulate`, body, { timeout: 30000 });

export const listFoldingUsers = () =>
  axios.get(`${API_BASE}/rinse/folding/users`, { timeout: 30000 });

export const listFoldingExcludedUsers = () =>
  axios.get(`${API_BASE}/rinse/folding/excluded-users`, { timeout: 30000 });

export const addFoldingExcludedUser = (body) =>
  axios.post(`${API_BASE}/rinse/folding/excluded-users`, body, { timeout: 30000 });

export const removeFoldingExcludedUser = (body) =>
  axios.delete(`${API_BASE}/rinse/folding/excluded-users`, { data: body, timeout: 30000 });

/** Admin: GET whether Rinse bag CSV export can run on the server (Node + scraper + env). */
export const getRinseBagExportConfig = () =>
  axios.get(`${API_BASE}/admin/rinse/bag-export/config`, { timeout: 15000 });

/**
 * Admin: run Playwright scrape on API host; returns CSV as blob on success.
 * Long timeout — many ticket pages can take several minutes.
 */
export const postRinseBagExport = () =>
  axios.post(`${API_BASE}/admin/rinse/bag-export`, {}, { responseType: "blob", timeout: 900000 });

/**
 * Admin: run Rinse portal scrape on the API and insert a draft upload batch (same pipeline as file upload).
 * Optional body: { batch_date: "YYYY-MM-DD" } (defaults to today on the server).
 * Prefer startRinseImportUploadBatchJob + polling — this call holds one HTTP request for the entire scrape.
 */
export const postRinseImportToUploadBatch = (body = {}) =>
  axios.post(`${API_BASE}/admin/rinse/import-upload-batch`, body, { timeout: 900000 });

/** Admin: enqueue async Rinse → draft batch import (returns job_id, HTTP 202). */
export const startRinseImportUploadBatchJob = (body = {}) =>
  axios.post(`${API_BASE}/admin/rinse/import-upload-batch/jobs`, body, { timeout: 120000 });

/** Admin: poll async Rinse import job until succeeded or failed.
 * Use a long timeout per request — after a large scrape the API can be busy parsing CSV / DB commit
 * for several minutes; a 120s cap caused false "timeout" while the job was still running. */
export const getRinseImportUploadBatchJob = (jobId) =>
  axios.get(`${API_BASE}/admin/rinse/import-upload-batch/jobs/${encodeURIComponent(jobId)}`, {
    timeout: 900000,
  });

/** Admin: request cancellation of a running / queued Rinse import job (Playwright scrape). */
export const cancelRinseImportUploadBatchJob = (jobId) =>
  axios.post(
    `${API_BASE}/admin/rinse/import-upload-batch/jobs/${encodeURIComponent(jobId)}/cancel`,
    {},
    { timeout: 60000 }
  );

export const getUploadConflicts = (batch_id = null, status = "PENDING") =>
  axios.get(`${API_BASE}/upload_conflicts`, {
    timeout: 30000,
    params: {
      ...(batch_id ? { batch_id } : {}),
      status
    }
  });

export const overrideUploadConflicts = (conflict_ids, overridden_by = "admin") =>
  axios.post(`${API_BASE}/upload_conflicts/override`, {
    conflict_ids,
    overridden_by
  });

/** Badge + Upload page — can exceed 30s when API workers are busy (e.g. Rinse scrape). */
export const getCurrentUploadBatch = () =>
  axios.get(`${API_BASE}/upload_batches/current`, { timeout: 120000 });

export const getUploadBatches = (params = {}) =>
  axios.get(`${API_BASE}/upload_batches`, {
    timeout: 30000,
    params: { range: "last_3_days", limit: 50, ...params },
  });

export const getUploadBatchRows = (batch_id, row_status = "") =>
  axios.get(`${API_BASE}/upload_batches/${batch_id}/rows`, {
    timeout: 30000,
    params: row_status ? { row_status } : {}
  });

export const overrideUploadBatchRow = (batch_id, row_id, payload) =>
  axios.post(`${API_BASE}/upload_batches/${batch_id}/rows/${row_id}/override`, payload);

export const deleteUploadBatchRow = (batch_id, row_id) =>
  axios.post(`${API_BASE}/upload_batches/${batch_id}/rows/${row_id}/delete`);

export const addUploadBatchRow = (batch_id, payload) =>
  axios.post(`${API_BASE}/upload_batches/${batch_id}/rows/add`, payload);

export const confirmUploadBatch = (batch_id, force_confirm = false) =>
  axios.post(`${API_BASE}/upload_batches/${batch_id}/confirm`, { force_confirm });

export const resetCurrentDraftBatch = () =>
  axios.post(`${API_BASE}/upload_batches/current/reset`);

export const resetAllUploadBatches = (cascade_data = true) =>
  axios.post(`${API_BASE}/upload_batches/reset_all`, { cascade_data });

export const deleteUploadBatch = (batch_id, cascade_data = true) =>
  axios.post(`${API_BASE}/upload_batches/${batch_id}/delete`, { cascade_data });

export const getDailyOperationalResetSettings = () =>
  axios.get(`${API_BASE}/maintenance/daily-operational-reset`);

export const putDailyOperationalResetSettings = (body) =>
  axios.put(`${API_BASE}/maintenance/daily-operational-reset`, body);

export const getOpsUiFlags = () => axios.get(`${API_BASE}/maintenance/ops-ui-flags`);

export const putOpsUiFlags = (body) => axios.put(`${API_BASE}/maintenance/ops-ui-flags`, body);

export const getSupplyUsage = (params) =>
  axios.get(`${API_BASE}/maintenance/supply-usage`, { params, timeout: 30000 });

export const getSupplyUsageDosages = () =>
  axios.get(`${API_BASE}/maintenance/supply-usage/dosages`, { timeout: 15000 });

export const getSupplyUsageSettings = () =>
  axios.get(`${API_BASE}/maintenance/supply-usage/settings`, { timeout: 15000 });

export const getSupplyUsageMappingRules = () =>
  axios.get(`${API_BASE}/maintenance/supply-usage/mapping-rules`, { timeout: 15000 });

export const updateSupplyUsageDosages = (body) =>
  axios.put(`${API_BASE}/maintenance/supply-usage/dosages`, body, { timeout: 15000 });

export const updateSupplyUsageMappingRules = (body) =>
  axios.put(`${API_BASE}/maintenance/supply-usage/mapping-rules`, body, { timeout: 15000 });

export const getMachineConfiguration = () =>
  axios.get(`${API_BASE}/maintenance/machine-configuration`, { timeout: 15000 });

export const updateMachineConfiguration = (body) =>
  axios.put(`${API_BASE}/maintenance/machine-configuration`, body, { timeout: 15000 });

export const listCheckoutHistorySnapshots = () =>
  axios.get(`${API_BASE}/checkout_history/snapshots`);

export const getCheckoutHistoryOrders = (snapshotId) =>
  axios.get(`${API_BASE}/checkout_history/snapshots/${snapshotId}/orders`);

export const getCheckoutHistoryCheckouts = (snapshotId) =>
  axios.get(`${API_BASE}/checkout_history/snapshots/${snapshotId}/checkouts`);

/* =========================================
   EMPLOYEES
========================================= */

export const getEmployees = () =>
  axios.get(`${API_BASE}/employees`);

/* =========================================
   ISSUES
========================================= */

export const getIssues = () =>
  axios.get(`${API_BASE}/issues`);

export const addIssue = (issue_name) =>
  axios.post(`${API_BASE}/issues/add`, {
    issue_name: issue_name
  });

/* =========================================
   ORDER PROCESSING
========================================= */

export const processOrder = (payload) =>
  axios.post(`${API_BASE}/order_processing`, payload);

export const submitProcessedOrder = (order_id, payload) =>
  axios.post(`${API_BASE}/orders/${order_id}/submit_processed`, payload);

export const uploadOrderTicket = (order_id, payload) =>
  axios.post(`${API_BASE}/orders/${order_id}/ticket`, payload);

export const getOrderTicket = (order_id) =>
  axios.get(`${API_BASE}/orders/${order_id}/ticket`);

export const deleteOrderTicket = (order_id) =>
  axios.delete(`${API_BASE}/orders/${order_id}/ticket`);

export const getOrderGamingSession = (order_id) =>
  axios.get(`${API_BASE}/orders/${order_id}/gaming/session`);

export const startOrderGamingSession = (order_id, body) =>
  axios.post(`${API_BASE}/orders/${order_id}/gaming/start`, body);

export const scanOrderGamingDryer = (order_id, body) =>
  axios.post(`${API_BASE}/orders/${order_id}/gaming/scan`, body);

export const completeOrderGamingTicket = (order_id, body) =>
  axios.post(`${API_BASE}/orders/${order_id}/gaming/complete`, body);

export const cancelOrderGamingSession = (order_id, body) =>
  axios.post(`${API_BASE}/orders/${order_id}/gaming/cancel`, body);

export const getOrderTickets = (params = {}) =>
  axios.get(`${API_BASE}/order_tickets`, { params });

export const getOrderDiscrepancies = (params = {}) =>
  axios.get(`${API_BASE}/orders/discrepancies`, { params });

/* =========================================
   FOLDER SHIFT
========================================= */

export const startFolderShift = (employee_id, start_time) =>
  axios.post(`${API_BASE}/folder_shift/start`, {
    employee_id,
    start_time
  });

export const getCurrentShift = () =>
  axios.get(`${API_BASE}/folder_shift/current`);

/* =========================================
   GEOFENCE / ATTENDANCE
========================================= */

export const getGeofenceConfig = () =>
  axios.get(`${API_BASE}/geofence/config`);

export const saveGeofenceConfig = (payload) =>
  axios.post(`${API_BASE}/geofence/config`, payload);

export const clearGeofenceConfig = () =>
  axios.delete(`${API_BASE}/geofence/config`);

export const punchAttendance = (payload) =>
  axios.post(`${API_BASE}/attendance/punch`, payload);

export const pingAttendanceLocation = (payload) =>
  axios.post(`${API_BASE}/attendance/location_ping`, payload);

export const getAttendanceAlerts = (since_id = null) =>
  axios.get(`${API_BASE}/attendance/alerts`, {
    params: since_id ? { since_id } : {}
  });

export const getAttendanceLive = () =>
  axios.get(`${API_BASE}/attendance/live`);

export const getAttendanceEventsToday = (employee_id) =>
  axios.get(`${API_BASE}/attendance/events_today`, {
    params: { employee_id }
  });

export const getAttendanceMyState = () =>
  axios.get(`${API_BASE}/attendance/my_state`);

export const punchAttendanceMy = (payload) =>
  axios.post(`${API_BASE}/attendance/my_punch`, payload);

export const getAttendancePayrollMonitor = (params = {}) =>
  axios.get(`${API_BASE}/attendance/payroll_monitor`, { params });

/* =========================================
   MAINTENANCE
========================================= */

export const getMaintenanceTasks = () =>
  axios.get(`${API_BASE}/maintenance/tasks`);

export const createMaintenanceTask = (payload) =>
  axios.post(`${API_BASE}/maintenance/tasks`, payload);

export const updateMaintenanceTask = (payload) =>
  axios.put(`${API_BASE}/maintenance/tasks`, payload);

export const deleteMaintenanceTask = (id) =>
  axios.delete(`${API_BASE}/maintenance/tasks`, {
    params: { id },
  });

export const getMaintenanceAssignments = (status = "") =>
  axios.get(`${API_BASE}/maintenance/assignments`, {
    params: status ? { status } : {}
  });

export const createMaintenanceAssignment = (payload) =>
  axios.post(`${API_BASE}/maintenance/assignments`, payload);

export const updateMaintenanceAssignment = (payload) =>
  axios.put(`${API_BASE}/maintenance/assignments`, payload);

export const deleteMaintenanceAssignment = (id) =>
  axios.delete(`${API_BASE}/maintenance/assignments`, {
    params: { id },
  });

export const getMaintenanceLogs = () =>
  axios.get(`${API_BASE}/maintenance/logs`);

export const createMaintenanceLog = (payload) =>
  axios.post(`${API_BASE}/maintenance/logs`, payload);

export const updateMaintenanceLog = (payload) =>
  axios.put(`${API_BASE}/maintenance/logs`, payload);

export const deleteMaintenanceLog = (id) =>
  axios.delete(`${API_BASE}/maintenance/logs`, {
    params: { id },
  });

export const getMaintenanceAgenda = () =>
  axios.get(`${API_BASE}/maintenance/agenda`);

/* =========================================
   INVENTORY (v2)
========================================= */

export const getInventoryDashboard = () =>
  axios.get(`${API_BASE}/inventory/dashboard`);

export const getInventoryMeta = () =>
  axios.get(`${API_BASE}/inventory/meta`);

export const getInventoryBootstrap = () =>
  axios.get(`${API_BASE}/inventory/bootstrap`);

export const getInventoryCategories = (params = {}) =>
  axios.get(`${API_BASE}/inventory/categories`, { params });

export const createInventoryCategory = (payload) =>
  axios.post(`${API_BASE}/inventory/categories`, payload);

export const updateInventoryCategory = (payload) =>
  axios.put(`${API_BASE}/inventory/categories`, payload);

export const getInventoryVendors = (params = {}) =>
  axios.get(`${API_BASE}/inventory/vendors`, { params });

export const createInventoryVendor = (payload) =>
  axios.post(`${API_BASE}/inventory/vendors`, payload);

export const updateInventoryVendor = (payload) =>
  axios.put(`${API_BASE}/inventory/vendors`, payload);

export const getInventoryItems = (params = {}) =>
  axios.get(`${API_BASE}/inventory/items`, { params });

export const createInventoryItem = (payload) =>
  axios.post(`${API_BASE}/inventory/items`, payload);

export const updateInventoryItem = (payload) =>
  axios.put(`${API_BASE}/inventory/items`, payload);

export const removeInventoryItem = (id) =>
  axios.delete(`${API_BASE}/inventory/items`, { params: { id } });

export const getInventoryStockCheckDraft = () =>
  axios.get(`${API_BASE}/inventory/stock-check/draft`);

export const saveInventoryStockCheckDraft = (payload) =>
  axios.post(`${API_BASE}/inventory/stock-check/draft`, payload);

export const submitInventoryStockCheck = (payload) =>
  axios.post(`${API_BASE}/inventory/stock-check/submit`, payload);

export const getInventoryReorderSuggestions = () =>
  axios.get(`${API_BASE}/inventory/reorder-suggestions`);

export const duplicateInventoryOrder = (orderId) =>
  axios.post(`${API_BASE}/inventory/orders/${orderId}/duplicate`);

export const getInventoryVendorDetail = (vendorId) =>
  axios.get(`${API_BASE}/inventory/vendors/${vendorId}`);

export const getInventoryItemHistory = (itemId, params = {}) =>
  axios.get(`${API_BASE}/inventory/items/${itemId}/history`, { params });

export const getInventoryReports = (params = {}) =>
  axios.get(`${API_BASE}/inventory/reports`, { params });

export const saveInventoryVarianceThreshold = (payload) =>
  axios.put(`${API_BASE}/inventory/settings/variance-threshold`, payload);

export const createInventoryAdjustment = (payload) =>
  axios.post(`${API_BASE}/inventory/adjustments`, payload);

export const getInventoryOrdersSummary = () =>
  axios.get(`${API_BASE}/inventory/orders/summary`);

export const getInventoryOrders = (params = {}) =>
  axios.get(`${API_BASE}/inventory/orders`, { params });

export const createInventoryOrder = (payload) =>
  axios.post(`${API_BASE}/inventory/orders`, payload);

export const updateInventoryOrder = (payload) =>
  axios.put(`${API_BASE}/inventory/orders`, payload);

export const receiveInventoryOrder = (orderId, payload) =>
  axios.post(`${API_BASE}/inventory/orders/${orderId}/receive`, payload);

export const getInventoryWeeklyOrderReport = (params = {}) =>
  axios.get(`${API_BASE}/inventory/reports/weekly-orders`, { params });

export const createInventoryAdjustment = (payload) =>
  axios.post(`${API_BASE}/inventory/adjustments`, payload);

export const saveInventoryCount = (payload) =>
  axios.post(`${API_BASE}/inventory/counts`, payload);

export const getBagSales = () =>
  axios.get(`${API_BASE}/inventory/bag_sales`);

export const createBagSale = (payload) =>
  axios.post(`${API_BASE}/inventory/bag_sales`, payload);

export const getLowStockItems = () =>
  axios.get(`${API_BASE}/inventory/low_stock`);

export const saveInventoryCountsBulk = (payload) =>
  axios.post(`${API_BASE}/inventory/counts/bulk`, payload);

export const createInventoryReorder = (payload) =>
  axios.post(`${API_BASE}/inventory/reorder`, payload);

export const getInventoryBagPrice = () =>
  axios.get(`${API_BASE}/inventory/bag_price`);

export const saveInventoryBagPrice = (payload) =>
  axios.post(`${API_BASE}/inventory/bag_price`, payload);

export const getInventoryReport = (params = {}) =>
  axios.get(`${API_BASE}/inventory/report`, { params });

/* =========================================
   TIME & ATTENDANCE / PAYROLL (Bearer: ta_token)
========================================= */

export const taLogin = (email, password) =>
  axios.post(`${API_BASE}/api/ta/auth/login`, { email, password });

/** Alias for AuthContext */
export const login = taLogin;

/** Single in-flight GET /api/ta/auth/me (legacy; prefer getTaBootstrap). */
let _taAuthMeInflight = null;
export const getMe = () => {
  if (_taAuthMeInflight) return _taAuthMeInflight;
  _taAuthMeInflight = axios.get(`${API_BASE}/api/ta/auth/me`).finally(() => {
    _taAuthMeInflight = null;
  });
  return _taAuthMeInflight;
};

function _primeClockPayrollCacheFromBootstrap(res) {
  const ui = res?.data?.clock_payroll_ui;
  if (ui && typeof ui === "object") {
    _clockPayrollUiCache = { res: { data: ui }, at: Date.now(), inflight: null };
  }
}

/** One round-trip: user + permissions + clock/payroll UI + optional session (replaces /me + /clock-payroll-ui + often /sessions/current). */
let _taBootstrapInflight = null;
export const getTaBootstrap = (params = {}) => {
  const hasCoords =
    params &&
    (params.latitude != null || params.longitude != null || params.lat != null || params.lng != null);
  if (!hasCoords && _taBootstrapInflight) return _taBootstrapInflight;
  const req = axios
    .get(`${API_BASE}/api/ta/bootstrap`, { params })
    .then((res) => {
      _primeClockPayrollCacheFromBootstrap(res);
      return res;
    })
    .finally(() => {
      if (!hasCoords) _taBootstrapInflight = null;
    });
  if (!hasCoords) _taBootstrapInflight = req;
  return req;
};

export const getMyGeofence = () => axios.get(`${API_BASE}/api/ta/me/geofence`);

export const getTaSessionCurrent = (params, extraConfig = {}) =>
  axios.get(`${API_BASE}/api/ta/sessions/current`, { params, ...extraConfig });

/** Tenant clock banner / geofence labels + payroll screen field visibility (cached; see invalidate). */
export const getClockPayrollUiSettings = () => {
  if (!hasAuthToken()) {
    return Promise.resolve({ data: { clock: {}, payroll: {} } });
  }
  const now = Date.now();
  if (_clockPayrollUiCache.res && now - _clockPayrollUiCache.at < CLOCK_PAYROLL_UI_TTL_MS) {
    return Promise.resolve(_clockPayrollUiCache.res);
  }
  if (_clockPayrollUiCache.inflight) return _clockPayrollUiCache.inflight;
  _clockPayrollUiCache.inflight = axios
    .get(`${API_BASE}/api/ta/clock-payroll-ui`)
    .then((res) => {
      _clockPayrollUiCache = { res, at: Date.now(), inflight: null };
      return res;
    })
    .catch((e) => {
      _clockPayrollUiCache.inflight = null;
      throw e;
    });
  return _clockPayrollUiCache.inflight;
};

export const putClockPayrollUiSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/admin/clock-payroll-ui`, body).then((res) => {
    invalidateClockPayrollUiSettingsCache();
    return res;
  });

export const taClockIn = (body) =>
  axios.post(`${API_BASE}/api/ta/sessions/clock-in`, body);

export const taClockOut = (body) =>
  axios.post(`${API_BASE}/api/ta/sessions/clock-out`, body);

export const taBreakStart = () =>
  axios.post(`${API_BASE}/api/ta/sessions/break/start`);

export const taBreakEnd = () =>
  axios.post(`${API_BASE}/api/ta/sessions/break/end`);

export const getTaskTrackingTasks = (params = {}) =>
  axios.get(`${API_BASE}/api/ta/job-tracking/job-names`, { params });

export const postTaskTrackingTask = (body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/job-names`, body);

export const patchTaskTrackingTask = (taskId, body) =>
  axios.patch(`${API_BASE}/api/ta/job-tracking/job-names/${taskId}`, body);

export const deleteTaskTrackingTask = (taskId) =>
  axios.delete(`${API_BASE}/api/ta/job-tracking/job-names/${taskId}`);

export const postTaskTrackingTasksReorder = (body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/job-names/reorder`, body);

export const postTaskTrackingSwitchTask = (body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/sessions/current/switch-task`, body);

export const getTaskTrackingReports = (params) =>
  axios.get(`${API_BASE}/api/ta/job-tracking/reports`, { params });

/** @deprecated use getTaskTrackingTasks */
export const getJobTrackingJobNames = getTaskTrackingTasks;
/** @deprecated use postTaskTrackingTask */
export const postJobTrackingJobName = postTaskTrackingTask;
/** @deprecated use patchTaskTrackingTask */
export const patchJobTrackingJobName = patchTaskTrackingTask;
/** @deprecated use postTaskTrackingTasksReorder */
export const postJobTrackingJobNamesReorder = postTaskTrackingTasksReorder;
/** @deprecated use postTaskTrackingSwitchTask */
export const postJobTrackingSwitchJob = postTaskTrackingSwitchTask;
/** @deprecated use getTaskTrackingReports */
export const getJobTrackingReports = getTaskTrackingReports;

export const postJobTrackingWaiveSessionForceCheckout = (sessionId, body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/sessions/${sessionId}/waive-force-checkout`, body);

export const postJobTrackingOverrideForceCheckoutTime = (sessionId, body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/sessions/${sessionId}/override-force-checkout-time`, body);

export const postJobTrackingAllowContinuation = (sessionId, body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/sessions/${sessionId}/continue`, body);

export const postJobTrackingUserForceCheckoutWaiver = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/job-tracking/users/${userId}/force-checkout-waiver`, body);

export const getJobTrackingUserForceCheckoutWaiver = (userId) =>
  axios.get(`${API_BASE}/api/ta/job-tracking/users/${userId}/force-checkout-waiver`);

export const getTaUsers = () => axios.get(`${API_BASE}/api/ta/users`);

/** 1099 contractors for current tenant (payroll_profiles + contractor_1099 lane). */
export const getContractors = () => axios.get(`${API_BASE}/api/ta/contractors`);

export const getContractorPrefill = (userId) =>
  axios.get(`${API_BASE}/api/ta/contractors/${userId}/prefill`);

export const getContractorPaymentSummaries = (userId) =>
  axios.get(`${API_BASE}/api/ta/contractors/${userId}/payment-summaries`);

export const getContractorPaymentYtd = (userId, year) =>
  axios.get(`${API_BASE}/api/ta/contractors/${userId}/payment-ytd`, {
    params: year != null ? { year } : {},
  });

export const postContractorPaymentSummary = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/contractors/${userId}/payment-summaries`, body);

/** Save invoice/payment receipt; user_id optional in body for manual temp/one-time. */
export const postContractorPaymentRecord = (body) =>
  axios.post(`${API_BASE}/api/ta/contractors/payment-records`, body);

export const getContractorManualPaymentRecords = () =>
  axios.get(`${API_BASE}/api/ta/contractors/payment-records`);

export const patchContractorPaymentRecord = (recordId, body) =>
  axios.patch(`${API_BASE}/api/ta/contractors/payment-records/${recordId}`, body);

export const deleteContractorPaymentRecord = (recordId) =>
  axios.delete(`${API_BASE}/api/ta/contractors/payment-records/${recordId}`);

export const getPayrollTimeRecords = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/time-records`, { params });

export const postPayrollTimeRecord = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/time-records`, body);

/** POST save avoids PATCH blocked by API CORS on some deployments. */
export const patchPayrollTimeRecord = (recordId, body) =>
  axios.post(`${API_BASE}/api/ta/payroll/time-records/${recordId}/save`, body);

export const postApprovePayrollTimeRecord = (recordId) =>
  axios.post(`${API_BASE}/api/ta/payroll/time-records/${recordId}/approve`, {});

export const postBulkApprovePayrollTimeRecords = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/time-records/bulk-approve`, body);

export const deletePayrollTimeRecord = (recordId) =>
  axios.delete(`${API_BASE}/api/ta/payroll/time-records/${recordId}`);

export const postAdjustSessionTimes = (sessionId, body) =>
  axios.post(`${API_BASE}/api/ta/sessions/${sessionId}/adjust-times`, body);

export const getPayrollTaxSettings = () =>
  axios.get(`${API_BASE}/api/ta/payroll/tax-settings`);

export const putPayrollTaxSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/payroll/tax-settings`, body);

export const getPayrollEmployeePto = (userId) =>
  axios.get(`${API_BASE}/api/ta/payroll/pto/${userId}`);

export const postPayrollEmployeePtoAdjust = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/payroll/pto/${userId}`, body);

export const getPayrollScheduleSettings = () =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/settings`);

export const postPayrollScheduleSettings = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule/settings`, body);

export const getPayrollSchedule = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule`, { params });

export const postPayrollScheduleEntry = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule`, body);

export const patchPayrollScheduleEntry = (entryId, body) =>
  axios.patch(`${API_BASE}/api/ta/payroll/schedule/${entryId}`, body);

export const deletePayrollScheduleEntry = (entryId) =>
  axios.delete(`${API_BASE}/api/ta/payroll/schedule/${entryId}`);

export const getPayrollFundingForecast = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/funding-forecast`, { params });

export const getPayrollCalendarSettings = () =>
  axios.get(`${API_BASE}/api/ta/payroll/calendar-settings`);

export const putPayrollCalendarSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/payroll/calendar-settings`, body);

export const getPayrollScheduleCoverageTargets = () =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/coverage-targets`);

export const postPayrollScheduleCoverageTargets = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule/coverage-targets`, body);

export const getPayrollPlanningMaintenance = () =>
  axios.get(`${API_BASE}/api/ta/payroll/planning-maintenance`);

export const putPayrollPlanningMaintenance = (body) =>
  axios.put(`${API_BASE}/api/ta/payroll/planning-maintenance`, body);

export const getPayrollScheduleWorkers = () =>
  axios.get(`${API_BASE}/api/ta/payroll/workers`);

export const getPayrollWorkerSchedulingProfile = (userId) =>
  axios.get(`${API_BASE}/api/ta/payroll/workers/by-user/${userId}/scheduling`);

export const putPayrollWorkerSchedulingProfile = (userId, body) =>
  axios.put(`${API_BASE}/api/ta/payroll/workers/by-user/${userId}/scheduling`, body);

export const getPayrollEmployerAffiliations = () =>
  axios.get(`${API_BASE}/api/ta/payroll/workers/employer-affiliations`, { timeout: 30000 });

export const putPayrollEmployerAffiliation = (userId, body) =>
  axios.put(`${API_BASE}/api/ta/payroll/workers/by-user/${userId}/employer-affiliation`, body, {
    timeout: 30000,
  });

export const getPayrollWorkerAvailability = (workerProfileId) =>
  axios.get(`${API_BASE}/api/ta/payroll/workers/${workerProfileId}/availability`);

export const postPayrollWorkerAvailability = (workerProfileId, body) =>
  axios.post(`${API_BASE}/api/ta/payroll/workers/${workerProfileId}/availability`, body);

export const getPayrollScheduleWeeklySummary = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/weekly-summary`, { params });

export const getPayrollScheduleOvertimeRisk = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/overtime-risk`, { params });

export const getPayrollScheduleReplacements = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/replacement-suggestions`, { params });

export const getPayrollSchedulePlan = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/plan`, { params });

export const postPayrollScheduleSaveDraft = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule/plan/save-draft`, body);

export const postPayrollSchedulePublish = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule/plan/publish`, body);

export const postPayrollScheduleGenerateRoster = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule/generate-roster`, body);

export const getPayrollScheduleSuggestions = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/suggestions`, { params });

export const getPayrollScheduleChangeLog = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/change-log`, { params });

export const getRosterShareLinks = () =>
  axios.get(`${API_BASE}/api/ta/payroll/schedule/roster-share-links`);

export const postRosterShareLink = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/schedule/roster-share-links`, body);

export const patchRosterShareLink = (linkId, body) =>
  axios.patch(`${API_BASE}/api/ta/payroll/schedule/roster-share-links/${linkId}`, body);

export const deleteRosterShareLink = (linkId) =>
  axios.delete(`${API_BASE}/api/ta/payroll/schedule/roster-share-links/${linkId}`);

export const getPublicRoster = (token, params) =>
  axios.get(`${API_BASE}/api/public/roster/${token}`, { params });

export const postPublicRosterVerify = (token, body) =>
  axios.post(`${API_BASE}/api/public/roster/${token}/verify`, body);

export const getPayrollDue = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/pay-due`, { params });

export const getWorkerPayments = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/worker-payments`, { params });

export const getPayoutBatches = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches`, { params });

export const postPayoutBatch = (body) =>
  axios.post(`${API_BASE}/api/ta/payroll/payout-batches`, body);

export const getPayoutBatch = (batchId, params) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}`, { params });

export const patchPayoutBatch = (batchId, body) =>
  axios.patch(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}`, body);

export const processPayoutBatch = (batchId) =>
  patchPayoutBatch(batchId, { action: "process_batch" });

export const deletePayoutBatch = (batchId) =>
  axios.delete(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}`);

export const getPayoutAccountantQueue = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches/accountant-queue`, { params });

export const getPayoutBatchDetails = (batchId) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/details`);

export const putPayoutBatchDetails = (batchId, body) =>
  axios.put(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/details`, body);

export const confirmPayoutPayment = (batchId) =>
  axios.post(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/confirm-payment`);

export const finalizePayoutDetails = (batchId) =>
  axios.post(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/finalize-details`);

export const unfinalizePayoutDetails = (batchId) =>
  axios.post(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/unfinalize-details`);

export const estimatePayoutTaxes = (batchId, body = {}) =>
  axios.post(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/estimate-taxes`, body);

export const postRefreshPriorBalances = (batchId, body = {}) =>
  axios.post(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/refresh-prior-balances`, body);

export const setPayoutDocumentMode = (batchId, documentMode) =>
  axios.put(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/document-mode`, {
    document_mode: documentMode,
  });

export const getPaystubUrl = (batchId, lineId) =>
  `${API_BASE}/api/ta/payroll/payout-batches/${batchId}/paystub/${lineId}`;

export const getPaystubHtml = (batchId, lineId, { preview = false, copy = "employee" } = {}) =>
  axios.get(getPaystubUrl(batchId, lineId), {
    params: {
      ...(preview ? { preview: 1 } : {}),
      ...(copy ? { copy } : {}),
    },
    responseType: "text",
  });

export const postPaystubPreviewHtml = (batchId, lineId, body) =>
  axios.post(
    `${API_BASE}/api/ta/payroll/payout-batches/${batchId}/paystub-preview/${lineId}`,
    body,
    { responseType: "text" },
  );

export const getBatchPaystubsHtml = (batchId, { preview = false, copy = "employee" } = {}) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/paystubs`, {
    params: {
      ...(preview ? { preview: 1 } : {}),
      ...(copy ? { copy } : {}),
    },
    responseType: "text",
  });

export const getPaystubArchiveMeta = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/paystub-archive/meta`, { params });

export const getEmployeePaystubArchiveHtml = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/paystub-archive`, {
    params,
    responseType: "text",
  });

export const getEmployerPayrollPacketHtml = (batchId, { preview = false } = {}) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/employer-packet`, {
    params: preview ? { preview: 1 } : {},
    responseType: "text",
  });

export const getPayRegisterHtml = (batchId, { preview = false } = {}) =>
  axios.get(`${API_BASE}/api/ta/payroll/payout-batches/${batchId}/pay-register`, {
    params: preview ? { preview: 1 } : {},
    responseType: "text",
  });

export const getPaymentReceiptUrl = (batchId, lineId) =>
  `${API_BASE}/api/ta/payroll/payout-batches/${batchId}/payment-receipt/${lineId}`;

export const getPaymentReceiptHtml = (batchId, lineId) =>
  axios.get(getPaymentReceiptUrl(batchId, lineId), { responseType: "text" });

export const getAccountantYtd = (params) =>
  axios.get(`${API_BASE}/api/ta/payroll/accountant/ytd`, { params });

export const computeContractorPayment = (body) =>
  axios.post(`${API_BASE}/api/ta/contractors/compute-payment`, body);

export const getTaUser = (id) => axios.get(`${API_BASE}/api/ta/users/${id}`);

export const createTaUser = (body) =>
  axios.post(`${API_BASE}/api/ta/users`, body);

export const updateTaUser = (id, body) =>
  axios.put(`${API_BASE}/api/ta/users/${id}`, body);

/** Removes payroll/TA profile only; Washpro login row stays (unified payroll). Legacy: deletes ta_users row. */
export const deleteTaUser = (id) => axios.delete(`${API_BASE}/api/ta/users/${id}`);

export const putUserGeofences = (userId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/geofences`, body);

export const putUserEmploymentCategories = (userId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/employment-categories`, body);

export const getUserEntityTags = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/entity-tags`);

export const putUserEntityTags = (userId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/entity-tags`, body);

export const getTaHrEmployerSettings = () =>
  axios.get(`${API_BASE}/api/ta/org/hr-employer-settings`);

export const putTaHrEmployerSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/org/hr-employer-settings`, body);

/** W-4 Step 3 credit rates per tax year (GET any user with HR access; PUT requires ta.settings). */
export const getTaTaxFormYearSettings = (taxYear) =>
  axios.get(`${API_BASE}/api/ta/org/tax-form-year-settings`, {
    params: { tax_year: taxYear },
  });

export const putTaTaxFormYearSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/org/tax-form-year-settings`, body, {
    headers: { "Content-Type": "application/json" },
  });

export const getTaUserHrProfile = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/hr-profile`);

export const putTaUserHrProfile = (userId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/hr-profile`, body, {
    headers: { "Content-Type": "application/json" },
  });

export const getHrTimelineMeta = () =>
  axios.get(`${API_BASE}/api/ta/hr-timeline/meta`);

export const getUserHrTimeline = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/hr-timeline`);

export const createUserHrTimelineEntry = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/users/${userId}/hr-timeline`, body);

export const updateUserHrTimelineEntry = (userId, entryId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/hr-timeline/${entryId}`, body);

export const deleteUserHrTimelineEntry = (userId, entryId) =>
  axios.delete(`${API_BASE}/api/ta/users/${userId}/hr-timeline/${entryId}`);

export const previewUserHrTimelineEmail = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/users/${userId}/hr-timeline/preview-email`, body);

export const getTaUserHrFormsInventory = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/hr-forms/inventory`);

const HR_FORM_DOWNLOAD_TIMEOUT_MS = 120000;

function hrFormBase64ToBlob(b64, contentType) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: contentType || "application/pdf" });
}

/**
 * Download HR form bytes via axios (same stack as profile/inventory loads).
 * Server returns JSON+base64 when Accept is application/json.
 */
export async function getTaUserHrForm(userId, formId, locale = "en") {
  try {
    const res = await axios.get(
      `${API_BASE}/api/ta/users/${userId}/hr-forms/${encodeURIComponent(formId)}`,
      {
        params: { locale },
        timeout: HR_FORM_DOWNLOAD_TIMEOUT_MS,
        validateStatus: () => true,
        headers: {
          Accept: "application/json",
        },
      },
    );
    const body = res.data;
    if (res.status >= 200 && res.status < 300 && body && typeof body === "object" && body.data_base64) {
      return {
        status: res.status,
        data: hrFormBase64ToBlob(body.data_base64, body.content_type),
        headers: {
          "content-type": body.content_type || "application/pdf",
          "x-suggested-filename": body.filename || "",
        },
      };
    }
    const ct = String(res.headers?.["content-type"] || "").toLowerCase();
    if (res.status >= 200 && res.status < 300 && (ct.includes("pdf") || ct.includes("octet-stream"))) {
      const blobRes = await axios.get(
        `${API_BASE}/api/ta/users/${userId}/hr-forms/${encodeURIComponent(formId)}`,
        {
          params: { locale },
          timeout: HR_FORM_DOWNLOAD_TIMEOUT_MS,
          responseType: "blob",
          validateStatus: () => true,
          headers: { Accept: "application/pdf" },
        },
      );
      return {
        status: blobRes.status,
        data: blobRes.data,
        headers: blobRes.headers || {},
      };
    }
    const errMsg =
      body && typeof body === "object" && typeof body.error === "string"
        ? body.error
        : `Download failed (HTTP ${res.status})`;
    return {
      status: res.status,
      data: new Blob([JSON.stringify({ error: errMsg })], { type: "application/json" }),
      headers: res.headers || {},
    };
  } catch (e) {
    const apiErr = e?.response?.data?.error;
    if (typeof apiErr === "string" && apiErr.trim()) {
      throw new Error(apiErr.trim());
    }
    if (e?.code === "ECONNABORTED" || /timeout/i.test(String(e?.message || ""))) {
      throw new Error("Download timed out. Try again.");
    }
    if (!e?.response) {
      throw new Error(
        e?.message ||
          `Cannot reach the API (${getWashproApiBase() || "unknown host"}). Hard-refresh after deploy.`,
      );
    }
    throw e;
  }
}

/** @deprecated Use getTaUserHrForm */
export const postTaUserHrForm = (userId, formId, body = {}) =>
  getTaUserHrForm(userId, formId, body?.locale || "en");

export const getTaUserHrFormI9 = (userId, locale = "en") => getTaUserHrForm(userId, "i9", locale);

/** @deprecated Use getTaUserHrFormI9 */
export const postTaUserHrFormI9 = (userId, locale = "en") => getTaUserHrFormI9(userId, locale);

export const getTaUserDocuments = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/documents`);

export const postTaUserDocument = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/users/${userId}/documents`, body);

export const uploadTaUserDocumentFile = (userId, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return axios.post(`${API_BASE}/api/ta/users/${userId}/documents/upload`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const putTaUserDocument = (userId, recordId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/documents/${recordId}`, body);

export const deleteTaUserDocument = (userId, recordId) =>
  axios.delete(`${API_BASE}/api/ta/users/${userId}/documents/${recordId}`);

/** Authenticated stream of an uploaded HR document (private blob proxy). */
export const getTaUserDocumentFile = (userId, recordId, opts = {}) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/documents/${recordId}/file`, {
    responseType: "blob",
    params: opts.download ? { download: 1 } : undefined,
  });

export const getDocumentCompliancePolicy = () =>
  axios.get(`${API_BASE}/api/ta/admin/document-compliance-policy`);

export const putDocumentCompliancePolicy = (body) =>
  axios.put(`${API_BASE}/api/ta/admin/document-compliance-policy`, body);

export const getExpiringDocuments = (params = {}) =>
  axios.get(`${API_BASE}/api/ta/admin/document-compliance/expiring`, { params });

export const getGeofences = () => axios.get(`${API_BASE}/api/ta/geofences`);

export const createGeofence = (body) =>
  axios.post(`${API_BASE}/api/ta/geofences`, body);

export const updateGeofence = (id, body) =>
  axios.put(`${API_BASE}/api/ta/geofences/${id}`, body);

export const deleteGeofence = (id) =>
  axios.delete(`${API_BASE}/api/ta/geofences/${id}`);

export const getOrgHrLookups = (params = {}) =>
  axios.get(`${API_BASE}/api/ta/org-hr-lookups`, { params });

export const createOrgHrLookup = (body) =>
  axios.post(`${API_BASE}/api/ta/org-hr-lookups`, body);

export const updateOrgHrLookup = (id, body) =>
  axios.put(`${API_BASE}/api/ta/org-hr-lookups/${id}`, body);

export const getHrFormsOrgSummary = () => axios.get(`${API_BASE}/api/ta/hr-forms/org-summary`);

/** Documents & Evidence center: all org document records + reminder_days_before */
export const getOrgDocumentRecords = () => axios.get(`${API_BASE}/api/ta/documents/org-records`);

/** Bulk download: ZIP of http(s) file_uri / evidence_uri for selected record ids (cap 120). */
export const exportOrgDocumentRecordsZip = (recordIds) =>
  axios.post(
    `${API_BASE}/api/ta/documents/org-records/export-zip`,
    { record_ids: recordIds },
    {
      responseType: "blob",
      headers: { "Cache-Control": "no-store", Pragma: "no-cache" },
    },
  );

export const getEmploymentCategories = () =>
  axios.get(`${API_BASE}/api/ta/employment-categories`);

export const createEmploymentCategory = (body) =>
  axios.post(`${API_BASE}/api/ta/employment-categories`, body);

export const updateEmploymentCategory = (id, body) =>
  axios.put(`${API_BASE}/api/ta/employment-categories/${id}`, body);

export const deleteEmploymentCategory = (id) =>
  axios.delete(`${API_BASE}/api/ta/employment-categories/${id}`);

export const getUserRates = (userId) =>
  axios.get(`${API_BASE}/api/ta/user-rates`, {
    params: userId ? { user_id: userId } : {},
  });

export const createUserRate = (body) =>
  axios.post(`${API_BASE}/api/ta/user-rates`, body);

export const updateUserRate = (id, body) =>
  axios.put(`${API_BASE}/api/ta/user-rates/${id}`, body);

export const deleteUserRate = (id) =>
  axios.delete(`${API_BASE}/api/ta/user-rates/${id}`);

export const getMonitorSessions = (params) =>
  axios.get(`${API_BASE}/api/ta/monitor/sessions`, { params });

export const getPayrollCycles = () =>
  axios.get(`${API_BASE}/api/ta/payroll-cycles`);

export const submitPayrollCycleForApproval = (cycleId) =>
  axios.post(`${API_BASE}/api/ta/payroll-cycles/${cycleId}/submit-for-approval`);

export const approvePayrollCycle = (cycleId) =>
  axios.post(`${API_BASE}/api/ta/payroll-cycles/${cycleId}/approve`);

export const patchSessionPayrollLine = (sessionId, body) =>
  axios.patch(`${API_BASE}/api/ta/sessions/${sessionId}/payroll-line`, body);

export const getPayrollPeriodSettings = () =>
  axios.get(`${API_BASE}/api/ta/admin/payroll-period`);

export const putPayrollPeriodSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/admin/payroll-period`, body);

export const getTaRoles = () => axios.get(`${API_BASE}/api/ta/roles`);

export const getTaSettings = () => axios.get(`${API_BASE}/api/ta/settings`);

export const putTaSettings = (body) =>
  axios.put(`${API_BASE}/api/ta/settings`, body);

export const getTaBagRates = () => axios.get(`${API_BASE}/api/ta/bag-rates`);

export const getPermissionMatrix = () =>
  axios.get(`${API_BASE}/api/ta/admin/permission-matrix`);

export const putRolePermissions = (roleId, permission_keys) =>
  axios.put(`${API_BASE}/api/ta/admin/roles/${roleId}/permissions`, {
    permission_keys,
  });

export const createTaAdminRole = (payload) =>
  axios.post(`${API_BASE}/api/ta/admin/roles`, payload);

export const deleteTaAdminRole = (roleId) =>
  axios.delete(`${API_BASE}/api/ta/admin/roles/${roleId}`);

export const getAuditLog = () => axios.get(`${API_BASE}/api/ta/audit-log`);

export const forceClockOut = (sessionId, remarks) =>
  axios.post(`${API_BASE}/api/ta/sessions/${sessionId}/force-clock-out`, {
    remarks,
  });

export const getTaExceptions = () =>
  axios.get(`${API_BASE}/api/ta/exceptions`);

// Daily Revenue & Cost
export const getDrcCostSettings = () =>
  axios.get(`${API_BASE}/finance/daily-revenue-cost/cost-settings`);

export const updateDrcCostSettings = (body) =>
  axios.put(`${API_BASE}/finance/daily-revenue-cost/cost-settings`, body);

export const getDrcCommercialAccounts = (params) =>
  axios.get(`${API_BASE}/finance/daily-revenue-cost/commercial-accounts`, { params });

export const createDrcCommercialAccount = (body) =>
  axios.post(`${API_BASE}/finance/daily-revenue-cost/commercial-accounts`, body);

export const updateDrcCommercialAccount = (id, body) =>
  axios.put(`${API_BASE}/finance/daily-revenue-cost/commercial-accounts/${id}`, body);

export const getDrcRinseWfTiers = () =>
  axios.get(`${API_BASE}/finance/daily-revenue-cost/rinse-wf-tiers`);

export const updateDrcRinseWfTiers = (body) =>
  axios.put(`${API_BASE}/finance/daily-revenue-cost/rinse-wf-tiers`, body);

export const getDailyRevenueEntry = (entryDate) =>
  axios.get(`${API_BASE}/finance/daily-revenue-cost/entries/${entryDate}`);

export const saveDailyRevenueEntry = (entryDate, body) =>
  axios.put(`${API_BASE}/finance/daily-revenue-cost/entries/${entryDate}`, body);

export const previewDailyRevenueEntry = (entryDate, body) =>
  axios.post(`${API_BASE}/finance/daily-revenue-cost/entries/${entryDate}/preview`, body);

export const getDrcDashboard = (params) =>
  axios.get(`${API_BASE}/finance/daily-revenue-cost/dashboard`, { params });

export const postDrcEntryWorkflow = (entryDate, body) =>
  axios.post(`${API_BASE}/finance/daily-revenue-cost/entries/${entryDate}/workflow`, body);

export { API_BASE };
