import axios from "axios";

const API_BASE =
  import.meta.env.VITE_API_BASE ||
  "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const t = localStorage.getItem("ta_token");
  if (t) {
    config.headers.Authorization = `Bearer ${t}`;
  }
  return config;
});

/* =========================================
   DASHBOARD / ORDERS (existing)
========================================= */

export const getDashboard = () => api.get("/dashboard");

export const getOrders = () => api.get("/orders");

export const updateOrder = (id, data) => api.put(`/orders/${id}`, data);

export const deleteOrder = (id) => api.delete(`/orders/${id}`);

/* =========================================
   CHECKOUT
========================================= */

export const checkoutOrder = (order_id, employee) =>
  api.post("/checkout", { order_id, employee });

export const checkoutBulk = (order_ids, employee) =>
  api.post("/checkout_bulk", { order_ids, employee });

/* =========================================
   UPLOAD ORDERS
========================================= */

export const uploadOrders = (formData) =>
  api.post("/upload_orders", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });

/* =========================================
   ISSUES
========================================= */

export const getIssues = () => api.get("/issues");

export const addIssue = (issue_name) => api.post("/issues/add", { issue_name });

/* =========================================
   ORDER PROCESSING
========================================= */

export const processOrder = (payload) => api.post("/order_processing", payload);

/* =========================================
   FOLDER SHIFT (legacy stub — optional backend)
========================================= */

export const startFolderShift = (employee_id, start_time) =>
  api.post("/folder_shift/start", { employee_id, start_time });

export const getCurrentShift = () => api.get("/folder_shift/current");

/* =========================================
   TIME & ATTENDANCE / PAYROLL
========================================= */

export const taLogin = (email, password) =>
  api.post("/api/ta/auth/login", { email, password });

export const login = taLogin;

export const getMe = () => api.get("/api/ta/auth/me");

export const getMyGeofence = () => api.get("/api/ta/me/geofence");

export const getTaSessionCurrent = (params) =>
  api.get("/api/ta/sessions/current", { params });

export const taClockIn = (body) => api.post("/api/ta/sessions/clock-in", body);

export const taClockOut = (body) => api.post("/api/ta/sessions/clock-out", body);

export const taBreakStart = () => api.post("/api/ta/sessions/break/start");

export const taBreakEnd = () => api.post("/api/ta/sessions/break/end");

export const getTaUsers = () => api.get("/api/ta/users");

export const getTaUser = (id) => api.get(`/api/ta/users/${id}`);

export const createTaUser = (body) => api.post("/api/ta/users", body);

export const updateTaUser = (id, body) => api.put(`/api/ta/users/${id}`, body);

export const putUserGeofences = (userId, body) =>
  api.put(`/api/ta/users/${userId}/geofences`, body);

export const putUserEmploymentCategories = (userId, body) =>
  api.put(`/api/ta/users/${userId}/employment-categories`, body);

export const getGeofences = () => api.get("/api/ta/geofences");

export const createGeofence = (body) => api.post("/api/ta/geofences", body);

export const updateGeofence = (id, body) => api.put(`/api/ta/geofences/${id}`, body);

export const getEmploymentCategories = () => api.get("/api/ta/employment-categories");

export const createEmploymentCategory = (body) =>
  api.post("/api/ta/employment-categories", body);

export const getUserRates = (userId) =>
  api.get("/api/ta/user-rates", { params: userId ? { user_id: userId } : {} });

export const createUserRate = (body) => api.post("/api/ta/user-rates", body);

export const getMonitorSessions = (params) =>
  api.get("/api/ta/monitor/sessions", { params });

export const getPayrollCycles = () => api.get("/api/ta/payroll-cycles");

export const getTaRoles = () => api.get("/api/ta/roles");

export const getTaSettings = () => api.get("/api/ta/settings");

export const putTaSettings = (body) => api.put("/api/ta/settings", body);

export const getAuditLog = () => api.get("/api/ta/audit-log");

export const forceClockOut = (sessionId, remarks) =>
  api.post(`/api/ta/sessions/${sessionId}/force-clock-out`, { remarks });

export const getTaExceptions = () => api.get("/api/ta/exceptions");

export { API_BASE, api };
