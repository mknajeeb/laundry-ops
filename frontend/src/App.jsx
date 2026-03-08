import { BrowserRouter, Routes, Route } from "react-router-dom";

import Sidebar from "./components/Sidebar";

import OrdersPage from "./pages/OrdersPage";
import ProductionPage from "./pages/ProductionPage";
import ScoreboardPage from "./pages/ScoreboardPage";
import MaintenancePage from "./pages/MaintenancePage";
import IssuePage from "./pages/IssuePage";
import EmployeesPage from "./pages/EmployeesPage";
import CheckoutPage from "./pages/Checkoutpage";
import Dashboard from "./pages/Dashboard";
import UploadPage from "./pages/UploadPage";

function App(){

  return(

    <BrowserRouter>

      <div className="app-layout">

        <Sidebar />

        <div className="main-content">

          <Routes>

            <Route path="/" element={<OrdersPage />} />

            <Route path="/dashboard" element={<Dashboard />} />

            <Route path="/orders" element={<OrdersPage />} />

            <Route path="/checkout" element={<CheckoutPage />} />

            <Route path="/upload" element={<UploadPage />} />

            <Route path="/employees" element={<EmployeesPage />} />

            <Route path="/issues" element={<IssuePage />} />

            <Route path="/production" element={<ProductionPage />} />

            <Route path="/scoreboard" element={<ScoreboardPage />} />

            <Route path="/maintenance" element={<MaintenancePage />} />

          </Routes>

        </div>

      </div>

    </BrowserRouter>

  )

}

export default App;