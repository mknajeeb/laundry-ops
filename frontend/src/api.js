import axios from "axios";

/* =========================================
   API BASE
========================================= */

const API_BASE =
  "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";

/* =========================================
   DASHBOARD
========================================= */

export const getDashboard = () =>
  axios.get(`${API_BASE}/dashboard`);

/* =========================================
   ORDERS
========================================= */

export const getOrders = () =>
  axios.get(`${API_BASE}/orders`);

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

export const resetAllUploadBatches = () =>
  axios.post(`${API_BASE}/upload_batches/reset_all`);

export const deleteUploadBatch = (batch_id) =>
  axios.post(`${API_BASE}/upload_batches/${batch_id}/delete`);

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
