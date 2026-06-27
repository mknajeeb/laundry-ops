import ContractorPrintLogo from "./ContractorPrintLogo";
import { companyContactMiniText, resolveCompanyContact } from "./companyContact";
import {
  contractorLetterheadClassName,
  contractorLogoClassName,
  isWashmateIssuer,
} from "./contractorLetterhead";
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
  const washmate = isWashmateIssuer(prefill);
  const company = escapeHtml(prefill?.company_name || "VeeWash");
  const contact = escapeHtml(companyContactMiniText(prefill));
  const companyHtml = washmate ? "" : `<span class="cform-mini-company">${company}</span>`;
  const contactHtml = contact
    ? `<span class="cform-mini-contact">${contact}</span>`
    : "";
  return (
    `<div class="cform-mini-head">` +
    `<img src="${logoSrc}" alt="" class="${logoClass}" onerror="this.onerror=null;this.src='${EMBEDDED_VEEWASH_LOGO}'" />` +
    companyHtml +
    contactHtml +
    `</div>`
  );
}

export function ContractorPrintLetterhead({ prefill, documentTitle, mini = false }) {
  const company = prefill?.company_name || "VeeWash";
  const washmate = isWashmateIssuer(prefill);
  const { address, phone, website, websiteLabel, showWebsite, showPhone } = resolveCompanyContact(prefill);
  const logoClass = contractorLogoClassName(prefill, mini);
  const miniContact = companyContactMiniText(prefill);

  if (mini) {
    return (
      <div className="cform-mini-head">
        <ContractorPrintLogo prefill={prefill} className={logoClass} />
        {!washmate ? <span className="cform-mini-company">{company}</span> : null}
        {miniContact ? <span className="cform-mini-contact">{miniContact}</span> : null}
      </div>
    );
  }

  return (
    <header className={contractorLetterheadClassName(prefill)}>
      <ContractorPrintLogo prefill={prefill} className={logoClass} />
      <div
        className={
          washmate ? "cform-letterhead-text cform-letterhead-text--washmate" : "cform-letterhead-text"
        }
      >
        {!washmate ? <div className="cform-company-name">{company}</div> : null}
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
export default function ContractorPrintShell({
  prefill,
  documentTitle,
  children,
  compact = false,
  offerLetter = false,
}) {
  const rootClass = [
    "contractor-print-root",
    compact && "contractor-print-root--one-page",
    offerLetter && "contractor-print-root--offer-letter",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={rootClass}>
      <ContractorPrintLetterhead prefill={prefill} documentTitle={documentTitle} />
      <div className="cform-body">{children}</div>
    </div>
  );
}
