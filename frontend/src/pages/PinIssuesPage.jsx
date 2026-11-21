/**
 * PIN hub → Issues management for supervisors and administrators.
 * Uses the same register, photos, and status APIs as the desktop Issues page.
 */
import PinIssuesFlow from "../opsMobile/PinIssuesFlow";
import PinModulePage from "./PinModulePage";

export default function PinIssuesPage({ onPinHubDone }) {
  return (
    <PinModulePage onPinHubDone={onPinHubDone}>
      {(nav) => <PinIssuesFlow onBack={nav.onBack} onLock={nav.onLock} />}
    </PinModulePage>
  );
}
