import { Navigate } from "react-router-dom";

/**
 * Employee PIN Revenue & Cost route retired — Management Revenue is the entry surface.
 * Historical mobile submissions remain in drc_mobile_section_submissions.
 */
export default function RevenueCostFloorPage() {
  return <Navigate to="/management/revenue" replace />;
}
