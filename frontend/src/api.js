import axios from "axios";

const API_BASE =
  "https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net";

export const getOrders = () => axios.get(`${API_BASE}/orders`);

export const getDashboard = () => axios.get(`${API_BASE}/dashboard`);