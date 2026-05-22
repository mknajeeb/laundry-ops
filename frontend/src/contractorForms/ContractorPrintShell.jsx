import ContractorPrintLogo from "./ContractorPrintLogo";
import { EMBEDDED_VEEWASH_LOGO } from "./contractorLogo";

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Repeat header on continuation pages when printing multi-section packets. */
export function miniHeadHtml(prefill) {
  const logoSrc = EMBEDDED_VEEWASH_LOGO;
  const company = escapeHtml(prefill?.company_name || "VeeWash");
  return `<div class="cform-mini-head"><img src="${logoSrc}" alt="" class="cform-logo-mini" onerror="this.onerror=null;this.src='${EMBEDDED_VEEWASH_LOGO}'" /><span class="cform-mini-company">${company}</span></div>`;
}

export function ContractorPrintLetterhead({ prefill, documentTitle, mini = false }) {
  const company = prefill?.company_name || "VeeWash";
  const address =
    prefill?.company_address || "10438 Jamaica Avenue, Richmond Hill, NY 11418";

  if (mini) {
    return (
      <div className="cform-mini-head">
        <ContractorPrintLogo prefill={prefill} className="cform-logo-mini" />
        <span className="cform-mini-company">{company}</span>
      </div>
    );
  }

  return (
    <header className="cform-letterhead">
      <ContractorPrintLogo prefill={prefill} className="cform-logo" />
      <div className="cform-letterhead-text">
        <div className="cform-company-name">{company}</div>
        <div className="cform-company-address">{address}</div>
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
