import { Navigate } from "react-router-dom";

/** Legacy PIN DRC floor — redirect to Management Revenue / Cash. */
export default function RevenueCostFloorPage() {
  return <Navigate to="/revenue-cash" replace />;
}
