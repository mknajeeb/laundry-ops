import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import { ISSUER_PROFILES, resolveIssuerEntity } from "./issuerProfiles";

/** Transparent-background VeeWash logo — public path for print/PDF and dashboard branding. */
export const EMBEDDED_VEEWASH_LOGO = VEEWASH_LOGO_URL;

export function contractorLogoSrc(prefill) {
  const entity = resolveIssuerEntity(prefill?.issued_by_entity);
  const profile = ISSUER_PROFILES[entity];
  if (profile?.organization_logo_url) return profile.organization_logo_url;
  return prefill?.organization_logo_url || EMBEDDED_VEEWASH_LOGO;
}
