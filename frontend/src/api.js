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

/* =========================================
   UPLOAD ORDERS
========================================= */

export const uploadOrders = (formData) =>
  axios.post(`${API_BASE}/upload_orders`, formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });

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