import PinScanChronologyFlow from "../opsMobile/PinScanChronologyFlow";
import PinModulePage from "./PinModulePage";

export default function PinScanPage({ onPinHubDone }) {
  return (
    <PinModulePage onPinHubDone={onPinHubDone}>
      {(nav) => <PinScanChronologyFlow onBack={nav.onBack} onLock={nav.onLock} />}
    </PinModulePage>
  );
}
