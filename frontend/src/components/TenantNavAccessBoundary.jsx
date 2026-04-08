import { Navigate, useLocation } from "react-router-dom";
import { tenantNavItemForPath, tenantNavItemVisible } from "../constants/tenantNav";

function isLoginPath(path) {
  const p = path || "";
  return p === "/login" || p.startsWith("/login/");
}

/**
 * Redirects to home when the current route matches a sidebar nav item the user may not access
 * (e.g. CHECKOUT-only user opens /dashboard).
 */
export default function TenantNavAccessBoundary({ user, payrollNavVisible = true, children }) {
  const { pathname } = useLocation();
  const p = pathname || "/";

  if (!user || isLoginPath(p)) return children;

  const item = tenantNavItemForPath(p);
  if (item && !tenantNavItemVisible(user, item, payrollNavVisible)) {
    return <Navigate to="/" replace />;
  }
  return children;
}
