/** Default VeeWash company contact shown on all printable contractor/payroll forms. */

export const VEEWASH_DEFAULT_ADDRESS = "10438 Jamaica Avenue, Richmond Hill, NY 11418";
export const VEEWASH_PHONE = "(917) 341-5161";
export const VEEWASH_WEBSITE = "https://veewash.com";
export const VEEWASH_WEBSITE_LABEL = "veewash.com";

export function resolveCompanyContact(prefill) {
  const website = prefill?.company_website || VEEWASH_WEBSITE;
  const websiteLabel = prefill?.company_website_label || VEEWASH_WEBSITE_LABEL;
  return {
    address: prefill?.company_address || VEEWASH_DEFAULT_ADDRESS,
    phone: prefill?.company_phone || VEEWASH_PHONE,
    website,
    websiteLabel,
    showWebsite: Boolean(website && websiteLabel),
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
  const { address, phone, website, websiteLabel, showWebsite } = resolveCompanyContact(prefill);
  const web = showWebsite
    ? ` · <a href="${escapeHtml(website)}">${escapeHtml(websiteLabel)}</a>`
    : "";
  return (
    `<div class="cform-company-address">${escapeHtml(address)}</div>` +
    `<div class="cform-company-contact">${escapeHtml(phone)}${web}</div>`
  );
}

/** Compact contact line for continuation-page mini headers. */
export function companyContactMiniText(prefill) {
  const { phone, websiteLabel, showWebsite } = resolveCompanyContact(prefill);
  return showWebsite ? `${phone} · ${websiteLabel}` : phone;
}
