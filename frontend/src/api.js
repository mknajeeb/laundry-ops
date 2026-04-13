import axios from "axios";

/* =========================================
   API BASE
========================================= */

const API_BASE =
  import.meta.env.VITE_API_BASE != null && import.meta.env.VITE_API_BASE !== ""
    ? import.meta.env.VITE_API_BASE
    : import.meta.env.DEV
      ? ""
      : "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";

/** No trailing slash; empty in dev when Vite proxy is used. */
export function getWashproApiBase() {
  return String(API_BASE || "").trim().replace(/\/+$/, "");
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

/* =========================================
   ORDERS
========================================= */

export const lookupOrdersByScan = (body) => axios.post(`${API_BASE}/orders/lookup_scan`, body);

export const getOrders = (options = {}) =>
  axios.get(`${API_BASE}/orders`, {
    params: {
      ...(options.include_all ? { include_all: 1 } : {}),
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
 */
export const postRinseImportToUploadBatch = (body = {}) =>
  axios.post(`${API_BASE}/admin/rinse/import-upload-batch`, body, { timeout: 900000 });

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

export const getCurrentUploadBatch = () =>
  axios.get(`${API_BASE}/upload_batches/current`, { timeout: 30000 });

export const getUploadBatches = (limit = 20) =>
  axios.get(`${API_BASE}/upload_batches`, {
    timeout: 30000,
    params: { limit }
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
   INVENTORY
========================================= */

export const getInventoryItems = () =>
  axios.get(`${API_BASE}/inventory/items`);

export const createInventoryItem = (payload) =>
  axios.post(`${API_BASE}/inventory/items`, payload);

export const updateInventoryItem = (payload) =>
  axios.put(`${API_BASE}/inventory/items`, payload);

export const removeInventoryItem = (id) =>
  axios.delete(`${API_BASE}/inventory/items`, {
    params: { id },
  });

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

export const getTaUsers = () => axios.get(`${API_BASE}/api/ta/users`);

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

export const getTaUserHrFormsInventory = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/hr-forms/inventory`);

/** locale: en | es | bilingual — AcroForm prefill where supported (I-9, W-4, W-9, etc.). */
export const postTaUserHrForm = (userId, formId, body = {}) =>
  axios.post(`${API_BASE}/api/ta/users/${userId}/hr-forms/${encodeURIComponent(formId)}`, body, {
    responseType: "blob",
    headers: { "Cache-Control": "no-store", Pragma: "no-cache" },
  });

export const postTaUserHrFormI9 = (userId, locale = "en") =>
  axios.post(
    `${API_BASE}/api/ta/users/${userId}/hr-forms/i9`,
    { locale },
    {
      responseType: "blob",
      headers: { "Cache-Control": "no-store", Pragma: "no-cache" },
    },
  );

export const getTaUserDocuments = (userId) =>
  axios.get(`${API_BASE}/api/ta/users/${userId}/documents`);

export const postTaUserDocument = (userId, body) =>
  axios.post(`${API_BASE}/api/ta/users/${userId}/documents`, body);

export const putTaUserDocument = (userId, recordId, body) =>
  axios.put(`${API_BASE}/api/ta/users/${userId}/documents/${recordId}`, body);

export const deleteTaUserDocument = (userId, recordId) =>
  axios.delete(`${API_BASE}/api/ta/users/${userId}/documents/${recordId}`);

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

export { API_BASE };
