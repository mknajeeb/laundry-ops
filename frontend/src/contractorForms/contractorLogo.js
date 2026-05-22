import embeddedVeeWashLogo from "../assets/veewash-logo.png";

/** White-background VeeWash logo — bundled for print/PDF (always used on contractor forms). */
export const EMBEDDED_VEEWASH_LOGO = embeddedVeeWashLogo;

export function contractorLogoSrc(_prefill) {
  return EMBEDDED_VEEWASH_LOGO;
}
