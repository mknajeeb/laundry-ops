import axios from "axios";

const API_BASE =
"https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";

/* ======================
   DASHBOARD
====================== */

export const getDashboard = () =>
  axios.get(`${API_BASE}/dashboard`);

/* ======================
   ORDERS
====================== */

export const getOrders = () =>
  axios.get(`${API_BASE}/orders`);

/* ======================
   UPLOAD ORDERS
====================== */

export const uploadOrders = (formData) =>
  axios.post(`${API_BASE}/upload_orders`, formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });