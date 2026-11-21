import PinPayrollFlow from "../opsMobile/PinPayrollFlow";
import PinModulePage from "./PinModulePage";

export default function PinPayrollPage({ onPinHubDone }) {
  return (
    <PinModulePage onPinHubDone={onPinHubDone}>
      {(nav) => <PinPayrollFlow onBack={nav.onBack} onLock={nav.onLock} />}
    </PinModulePage>
  );
}
