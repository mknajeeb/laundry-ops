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

const AUTH_TOKEN_KEY = "washpro_token";
const AUTH_USER_KEY = "washpro_user";

export const getAuthToken = () => localStorage.getItem(AUTH_TOKEN_KEY) || "";
export const setAuthSession = ({ token, user }) => {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (user) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new CustomEvent("washpro-session-changed"));
};
export const clearAuthSession = () => {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
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

export const authLogin = (username, password, organization_slug) =>
  axios.post(`${API_BASE}/auth/login`, {
    username,
    password,
    ...(organization_slug != null && String(organization_slug).trim() !== ""
      ? { organization_slug: String(organization_slug).trim().toLowerCase() }
      : {}),
  });

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

export const authMe = () =>
  axios.get(`${API_BASE}/auth/me`);

export const putAuthPassword = (body) =>
  axios.put(`${API_BASE}/auth/me/password`, body);

export const authLogout = () =>
  axios.post(`${API_BASE}/auth/logout`);

/** Public: branding for login when user enters organization slug */
export const getPublicOrgBranding = (slug) =>
  axios.get(`${API_BASE}/api/public/organization/branding`, {
    params: { slug: String(slug || "").trim().toLowerCase() },
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

export const getMe = () => axios.get(`${API_BASE}/api/ta/auth/me`);

export const getMyGeofence = () => axios.get(`${API_BASE}/api/ta/me/geofence`);

export const getTaSessionCurrent = (params) =>
  axios.get(`${API_BASE}/api/ta/sessions/current`, { params });

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

export const getGeofences = () => axios.get(`${API_BASE}/api/ta/geofences`);

export const createGeofence = (body) =>
  axios.post(`${API_BASE}/api/ta/geofences`, body);

export const updateGeofence = (id, body) =>
  axios.put(`${API_BASE}/api/ta/geofences/${id}`, body);

export const deleteGeofence = (id) =>
  axios.delete(`${API_BASE}/api/ta/geofences/${id}`);

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
