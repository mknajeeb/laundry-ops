import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { tenantNavItemForPath, tenantNavItemVisible } from "../constants/tenantNav";
import { userSatisfiesRoleGate } from "../utils/platformAccess";

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
  const { hasPerm, loading: authLoading } = useAuth();
  const p = pathname || "/";

  if (!user || isLoginPath(p)) return children;

  const item = tenantNavItemForPath(p);
  /** Avoid sending users home while TA permissions are still loading (role gate would fail first). */
  if (
    item?.permissionsAnyOf?.length &&
    authLoading &&
    item.roles?.length &&
    !userSatisfiesRoleGate(user, item.roles)
  ) {
    return children;
  }
  if (item && !tenantNavItemVisible(user, item, payrollNavVisible, hasPerm)) {
    return <Navigate to="/" replace />;
  }
  return children;
}
