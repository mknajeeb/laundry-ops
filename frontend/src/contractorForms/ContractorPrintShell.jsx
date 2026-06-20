import ContractorPrintLogo from "./ContractorPrintLogo";
import { companyContactMiniText, resolveCompanyContact } from "./companyContact";
import { contractorLogoClassName } from "./contractorLetterhead";
import { contractorLogoSrc, EMBEDDED_VEEWASH_LOGO } from "./contractorLogo";

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Repeat header on continuation pages when printing multi-section packets. */
export function miniHeadHtml(prefill) {
  const logoSrc = contractorLogoSrc(prefill);
  const logoClass = contractorLogoClassName(prefill, true);
  const company = escapeHtml(prefill?.company_name || "VeeWash");
  const contact = escapeHtml(companyContactMiniText(prefill));
  const contactHtml = contact
    ? `<span class="cform-mini-contact">${contact}</span>`
    : "";
  return (
    `<div class="cform-mini-head">` +
    `<img src="${logoSrc}" alt="" class="${logoClass}" onerror="this.onerror=null;this.src='${EMBEDDED_VEEWASH_LOGO}'" />` +
    `<span class="cform-mini-company">${company}</span>` +
    contactHtml +
    `</div>`
  );
}

export function ContractorPrintLetterhead({ prefill, documentTitle, mini = false }) {
  const company = prefill?.company_name || "VeeWash";
  const { address, phone, website, websiteLabel, showWebsite, showPhone } = resolveCompanyContact(prefill);
  const logoClass = contractorLogoClassName(prefill, mini);
  const miniContact = companyContactMiniText(prefill);

  if (mini) {
    return (
      <div className="cform-mini-head">
        <ContractorPrintLogo prefill={prefill} className={logoClass} />
        <span className="cform-mini-company">{company}</span>
        {miniContact ? <span className="cform-mini-contact">{miniContact}</span> : null}
      </div>
    );
  }

  return (
    <header className="cform-letterhead">
      <ContractorPrintLogo prefill={prefill} className={logoClass} />
      <div className="cform-letterhead-text">
        <div className="cform-company-name">{company}</div>
        <div className="cform-company-address">{address}</div>
        {showPhone || showWebsite ? (
          <div className="cform-company-contact">
            {showPhone ? phone : null}
            {showPhone && showWebsite ? " · " : null}
            {showWebsite ? (
              <a href={website} className="cform-company-website">
                {websiteLabel}
              </a>
            ) : null}
          </div>
        ) : null}
        {documentTitle ? <h1 className="cform-document-title">{documentTitle}</h1> : null}
      </div>
    </header>
  );
}

/** Wraps printable contractor content with branded header and print-safe layout. */
export default function ContractorPrintShell({ prefill, documentTitle, children }) {
  return (
    <div className="contractor-print-root">
      <ContractorPrintLetterhead prefill={prefill} documentTitle={documentTitle} />
      <div className="cform-body">{children}</div>
    </div>
  );
}
