import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Package,
  Upload,
  Users,
  Wrench,
  ClipboardList,
  BarChart3,
  AlertTriangle,
  Clock,
  LineChart,
  Settings2,
  LogIn,
  LogOut,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";

function Sidebar() {
  const location = useLocation();
  const { token, logout, hasPerm } = useAuth();

  const menu = [
    { label: "Dashboard", path: "/dashboard", icon: <LayoutDashboard size={18} /> },
    { label: "Orders", path: "/orders", icon: <Package size={18} /> },
    { label: "Checkout", path: "/checkout", icon: <ClipboardList size={18} /> },
    { label: "Upload", path: "/upload", icon: <Upload size={18} /> },
    { label: "Production", path: "/production", icon: <Package size={18} /> },
    { label: "Issues", path: "/issues", icon: <AlertTriangle size={18} /> },
    { label: "Scoreboard", path: "/scoreboard", icon: <BarChart3 size={18} /> },
    { label: "Maintenance", path: "/maintenance", icon: <Wrench size={18} /> },
  ];

  const taMenu = [
    { label: "Time clock", path: "/time-clock", icon: <Clock size={18} />, show: true },
    {
      label: "Payroll monitor",
      path: "/payroll-monitor",
      icon: <LineChart size={18} />,
      show: hasPerm("ta.monitor"),
    },
    {
      label: "Users",
      path: "/employees",
      icon: <Users size={18} />,
      show: hasPerm("users.view"),
    },
    {
      label: "Attendance setup",
      path: "/attendance-setup",
      icon: <Settings2 size={18} />,
      show: hasPerm("ta.settings"),
    },
  ];

  return (
    <div className="sidebar">
      <h2>LaundryOps</h2>

      <div className="sidebar-menu">
        {menu.map((item) => {
          const active = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`menu-item ${active ? "menu-active" : ""}`}
            >
              {item.icon}
              <span>{item.label}</span>
            </Link>
          );
        })}

        <div style={{ margin: "12px 0 6px", fontSize: 11, opacity: 0.65 }}>Time &amp; pay</div>
        {taMenu
          .filter((item) => item.show)
          .map((item) => {
            const active = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`menu-item ${active ? "menu-active" : ""}`}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            );
          })}

        {token ? (
          <button
            type="button"
            className="menu-item"
            onClick={logout}
            style={{ border: "none", background: "transparent", cursor: "pointer", width: "100%", textAlign: "left" }}
          >
            <LogOut size={18} />
            <span>Sign out</span>
          </button>
        ) : (
          <Link to="/login" className={`menu-item ${location.pathname === "/login" ? "menu-active" : ""}`}>
            <LogIn size={18} />
            <span>Sign in</span>
          </Link>
        )}
      </div>
    </div>
  );
}

export default Sidebar;