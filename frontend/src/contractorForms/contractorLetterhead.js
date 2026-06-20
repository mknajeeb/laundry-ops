import { resolveIssuerEntity } from "./issuerProfiles";

export function contractorLogoClassName(prefill, mini = false) {
  const isWashmate = resolveIssuerEntity(prefill?.issued_by_entity) === "washmate";
  if (mini) {
    return isWashmate ? "cform-logo-mini cform-logo-mini-washmate" : "cform-logo-mini";
  }
  return isWashmate ? "cform-logo cform-logo-washmate" : "cform-logo";
}
