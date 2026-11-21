import { useMemo } from "react";
import PinMachinesFlow from "../opsMobile/PinMachinesFlow";
import { loadPinHubSession } from "../utils/pinHubSession";
import PinModulePage from "./PinModulePage";

export function DevPinMachinesPreviewPage() {
  const machines = [
    { machine_code: "W23-30-VW", machine_type: "washer", display_number: "W23-30-VW", operational_status: "operational", capacity_lbs: 30, cleaning_eligible: true },
    {
      machine_code: "W24-30-VW",
      machine_type: "washer",
      display_number: "W24-30-VW",
      operational_status: "out_of_service",
      capacity_lbs: 30,
      cleaning_eligible: true,
      exclusion_review: true,
      remarks: "Bearing noise",
      issues: [{ id: 1842, status: "open", location_label: "W24-30-VW" }],
      events: [{ event_type: "status_changed", actor_user_id: 12, detail: "operational → out_of_service" }],
    },
    { machine_code: "D1-50-VW", machine_type: "dryer", display_number: "D1-50-VW", operational_status: "operational", capacity_lbs: 50, cleaning_eligible: true },
  ];
  return (
    <PinMachinesFlow
      onBack={() => {}}
      onLock={() => {}}
      orgSlug="veewash"
      preview={{ machines, canUpdate: true }}
    />
  );
}

export default function PinMachinesPage({ onPinHubDone }) {
  const slug = useMemo(() => loadPinHubSession()?.organization_slug || "", []);
  return (
    <PinModulePage onPinHubDone={onPinHubDone}>
      {(nav) => <PinMachinesFlow onBack={nav.onBack} onLock={nav.onLock} orgSlug={slug} />}
    </PinModulePage>
  );
}
