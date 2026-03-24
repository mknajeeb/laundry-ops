import { BrowserRouter, Routes, Route } from "react-router-dom";

import Sidebar from "./components/Sidebar";
import ProtectedRoute from "./components/ProtectedRoute";

import Dashboard from "./pages/Dashboard";
import OrdersPage from "./pages/OrdersPage";
import CheckoutPage from "./pages/CheckoutPage";
import UploadPage from "./pages/UploadPage";
import EmployeesPage from "./pages/EmployeesPage";
import IssuePage from "./pages/IssuePage";
import ProductionPage from "./pages/ProductionPage";
import ScoreboardPage from "./pages/ScoreboardPage";
import MaintenancePage from "./pages/MaintenancePage";
import LoginPage from "./pages/LoginPage";
import TimeClockPage from "./pages/TimeClockPage";
import PayrollMonitorPage from "./pages/PayrollMonitorPage";
import AttendanceSetupPage from "./pages/AttendanceSetupPage";

function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <div className="main-content">
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<Dashboard />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/checkout" element={<CheckoutPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route
              path="/employees"
              element={
                <ProtectedRoute>
                  <EmployeesPage />
                </ProtectedRoute>
              }
            />
            <Route path="/issues" element={<IssuePage />} />
            <Route path="/production" element={<ProductionPage />} />
            <Route path="/scoreboard" element={<ScoreboardPage />} />
            <Route path="/maintenance" element={<MaintenancePage />} />
            <Route
              path="/time-clock"
              element={
                <ProtectedRoute>
                  <TimeClockPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/payroll-monitor"
              element={
                <ProtectedRoute>
                  <PayrollMonitorPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/attendance-setup"
              element={
                <ProtectedRoute>
                  <AttendanceSetupPage />
                </ProtectedRoute>
              }
            />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

export default App;