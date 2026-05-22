import { resolveOrgLogoUrl } from "../utils/resolveOrgLogoUrl";
import embeddedVeeWashLogo from "../assets/veewash-logo.png";

/** Bundled logo — always available in production print/PDF (no broken /assets path). */
export const EMBEDDED_VEEWASH_LOGO = embeddedVeeWashLogo;

export function contractorLogoSrc(prefill) {
  const org = resolveOrgLogoUrl(prefill?.organization_logo_url);
  return org || EMBEDDED_VEEWASH_LOGO;
}
