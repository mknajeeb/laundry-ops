import { resolveIssuerEntity } from "./issuerProfiles";

export function isWashmateIssuer(prefill) {
  return resolveIssuerEntity(prefill?.issued_by_entity) === "washmate";
}

export function contractorLetterheadClassName(prefill) {
  return isWashmateIssuer(prefill)
    ? "cform-letterhead cform-letterhead--washmate"
    : "cform-letterhead";
}

export function contractorLogoClassName(prefill, mini = false) {
  const isWashmate = isWashmateIssuer(prefill);
  if (mini) {
    return isWashmate ? "cform-logo-mini cform-logo-mini-washmate" : "cform-logo-mini";
  }
  return isWashmate ? "cform-logo cform-logo-washmate" : "cform-logo";
}
