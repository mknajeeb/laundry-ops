/**
 * PIN hub → Team Status (manager attendance/role roster).
 * Requires pin-hub app session from EmployeePinHub unlock with team_status.
 */
import TeamStatusFlow from "../opsMobile/TeamStatusFlow";
import PinModulePage from "./PinModulePage";

export default function TeamStatusPage({ onPinHubDone }) {
  return (
    <PinModulePage onPinHubDone={onPinHubDone}>
      {(nav) => <TeamStatusFlow onBack={nav.onBack} onLock={nav.onLock} />}
    </PinModulePage>
  );
}
