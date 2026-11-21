import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import PinOpsDashboardFlow from "../opsMobile/PinOpsDashboardFlow";
import { loadPinHubSession } from "../utils/pinHubSession";
import PinModulePage from "./PinModulePage";

export default function PinDashboardPage({ onPinHubDone }) {
  const navigate = useNavigate();
  const onOpen = useCallback(
    (module) => {
      const slug = loadPinHubSession()?.organization_slug || "";
      const state = { fromDashboard: true };
      if (module === "issues") navigate("/pin-issues", { state });
      else if (module === "scan") navigate("/pin-scan", { state });
      else if (module === "payroll") navigate("/pin-payroll", { state });
      else if (module === "team") navigate("/team-status", { state });
      else if (module === "tasks" && slug) {
        navigate(`/attendance/cleaning-tasks/review/${encodeURIComponent(slug)}?from=hub`);
      }
    },
    [navigate],
  );

  return (
    <PinModulePage onPinHubDone={onPinHubDone}>
      {(nav) => <PinOpsDashboardFlow onBack={nav.onBack} onLock={nav.onLock} onOpen={onOpen} />}
    </PinModulePage>
  );
}
