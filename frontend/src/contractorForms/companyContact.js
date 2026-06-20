/** Default VeeWash company contact shown on all printable contractor/payroll forms. */

export const VEEWASH_DEFAULT_ADDRESS = "10438 Jamaica Avenue, Richmond Hill, NY 11418";
export const VEEWASH_PHONE = "(917) 341-5161";
export const VEEWASH_WEBSITE = "https://veewash.com";
export const VEEWASH_WEBSITE_LABEL = "veewash.com";

export function resolveCompanyContact(prefill) {
  const entity = String(prefill?.issued_by_entity || "").toLowerCase();
  const isWashmate = entity === "washmate";

  const rawPhone = prefill?.company_phone;
  const phone =
    rawPhone != null && String(rawPhone).trim() !== ""
      ? String(rawPhone).trim()
      : isWashmate
        ? ""
        : VEEWASH_PHONE;

  const rawWebsite = prefill?.company_website;
  const website =
    rawWebsite != null && String(rawWebsite).trim() !== ""
      ? String(rawWebsite).trim()
      : isWashmate
        ? ""
        : VEEWASH_WEBSITE;

  const rawWebsiteLabel = prefill?.company_website_label;
  const websiteLabel =
    rawWebsiteLabel != null && String(rawWebsiteLabel).trim() !== ""
      ? String(rawWebsiteLabel).trim()
      : isWashmate
        ? ""
        : VEEWASH_WEBSITE_LABEL;

  return {
    address: prefill?.company_address || VEEWASH_DEFAULT_ADDRESS,
    phone,
    website,
    websiteLabel,
    showWebsite: Boolean(website && websiteLabel),
    showPhone: Boolean(phone),
  };
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Letterhead contact block for markdown/HTML string builders. */
export function companyContactHtml(prefill) {
  const { address, phone, website, websiteLabel, showWebsite, showPhone } = resolveCompanyContact(prefill);
  if (!showPhone && !showWebsite) {
    return `<div class="cform-company-address">${escapeHtml(address)}</div>`;
  }
  const web = showWebsite
    ? ` · <a href="${escapeHtml(website)}">${escapeHtml(websiteLabel)}</a>`
    : "";
  const phonePart = showPhone ? escapeHtml(phone) : "";
  return (
    `<div class="cform-company-address">${escapeHtml(address)}</div>` +
    `<div class="cform-company-contact">${phonePart}${web}</div>`
  );
}

/** Compact contact line for continuation-page mini headers. */
export function companyContactMiniText(prefill) {
  const { phone, websiteLabel, showWebsite, showPhone } = resolveCompanyContact(prefill);
  if (!showPhone && !showWebsite) return "";
  if (showPhone && showWebsite) return `${phone} · ${websiteLabel}`;
  if (showPhone) return phone;
  return websiteLabel;
}
