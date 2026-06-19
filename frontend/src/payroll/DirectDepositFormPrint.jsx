import ContractorPrintLogo from "../contractorForms/ContractorPrintLogo";
import { resolveCompanyContact } from "../contractorForms/companyContact";
import { VEEWASH_BRAND, veewashPrintCssVars } from "../theme/veewashBrand";
import { maskTaxIdLast4, normalizeTaxIdDigits } from "../utils/validation";

function FieldRow({ label, value, wide }) {
  return (
    <div className={`vw-field${wide ? " vw-field--wide" : ""}`}>
      <span className="vw-field-label">{label}</span>
      <span className="vw-field-value">{value || "\u00a0"}</span>
    </div>
  );
}

function CheckPill({ label, checked }) {
  return (
    <span className={`vw-pill${checked ? " vw-pill--on" : ""}`}>
      <span className="vw-pill-dot" aria-hidden />
      {label}
    </span>
  );
}

function Section({ num, title, children }) {
  return (
    <section className="vw-card">
      <div className="vw-card-head">
        <span className="vw-card-num">{num}</span>
        <h2 className="vw-card-title">{title}</h2>
      </div>
      <div className="vw-card-body">{children}</div>
    </section>
  );
}

/**
 * VeeWash-branded employee information & direct deposit authorization (print/PDF).
 */
export default function DirectDepositFormPrint({ prefill = {} }) {
  const p = prefill || {};
  const contact = resolveCompanyContact(p);
  const dd = p.direct_deposit || {};
  const payType = String(p.pay_type || "hourly").toLowerCase();
  const payFreq = String(p.pay_frequency || "weekly").toLowerCase();
  const filing = String(p.federal_filing_status || "single").toLowerCase();
  const acctType = String(dd.account_type || "checking").toLowerCase();
  const stateDisplay = String(p.state || "").trim().toUpperCase();

  return (
    <div className="vw-ddf-root">
      <style>{`
        ${veewashPrintCssVars()}
        .vw-ddf-root {
          font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
          font-size: 10pt;
          line-height: 1.5;
          color: var(--vw-ink);
          width: 186mm;
          max-width: 186mm;
          margin: 0 auto;
          background: var(--vw-surface, #fff);
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }
        .vw-ddf-hero {
          background: ${VEEWASH_BRAND.gradient};
          border-radius: ${VEEWASH_BRAND.radius};
          padding: 0.2in 0.24in 0.18in;
          color: #fff;
          display: flex;
          gap: 0.18in;
          align-items: flex-start;
          margin-bottom: 0.16in;
          box-shadow: ${VEEWASH_BRAND.shadow};
          position: relative;
          overflow: hidden;
        }
        .vw-ddf-hero::after {
          content: "";
          position: absolute;
          top: 0;
          right: 0;
          width: 1.2in;
          height: 100%;
          background: linear-gradient(90deg, transparent, rgba(196, 160, 82, 0.18));
          pointer-events: none;
        }
        .vw-ddf-logo {
          width: 0.85in;
          height: 0.85in;
          min-width: 0.85in;
          object-fit: contain;
          background: rgba(255,255,255,0.95);
          border-radius: ${VEEWASH_BRAND.radiusSm};
          padding: 0.04in;
        }
        .vw-ddf-hero-text { flex: 1; min-width: 0; position: relative; z-index: 1; }
        .vw-ddf-company {
          font-size: 17pt;
          font-weight: 800;
          letter-spacing: -0.02em;
          line-height: 1.15;
        }
        .vw-ddf-tagline {
          font-size: 8.5pt;
          opacity: 0.92;
          margin-top: 0.04in;
          font-weight: 500;
        }
        .vw-ddf-doc-title {
          font-size: 11.5pt;
          font-weight: 700;
          margin: 0.12in 0 0;
          padding-top: 0.1in;
          border-top: 1px solid rgba(255,255,255,0.28);
          letter-spacing: 0.01em;
        }
        .vw-ddf-gold-bar {
          height: 3px;
          background: linear-gradient(90deg, ${VEEWASH_BRAND.gold}, ${VEEWASH_BRAND.teal});
          border-radius: 2px;
          margin-bottom: 0.14in;
        }
        .vw-card {
          background: ${VEEWASH_BRAND.primaryLight};
          border: 1px solid ${VEEWASH_BRAND.border};
          border-radius: ${VEEWASH_BRAND.radius};
          margin-bottom: 0.12in;
          overflow: hidden;
          page-break-inside: avoid;
        }
        .vw-card-head {
          display: flex;
          align-items: center;
          gap: 0.1in;
          padding: 0.1in 0.14in;
          background: #fff;
          border-bottom: 1px solid ${VEEWASH_BRAND.borderSoft};
        }
        .vw-card-num {
          width: 0.26in;
          height: 0.26in;
          border-radius: 50%;
          background: ${VEEWASH_BRAND.primary};
          color: #fff;
          font-size: 9pt;
          font-weight: 800;
          display: grid;
          place-items: center;
          flex-shrink: 0;
        }
        .vw-card-title {
          font-size: 10.5pt;
          font-weight: 700;
          color: ${VEEWASH_BRAND.primaryDark};
          margin: 0;
        }
        .vw-card-body {
          padding: 0.12in 0.14in 0.14in;
          background: #fff;
        }
        .vw-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 0.1in 0.12in;
        }
        .vw-grid--2 { grid-template-columns: 1fr 1fr; }
        .vw-field { display: flex; flex-direction: column; gap: 0.03in; min-width: 0; }
        .vw-field--wide { grid-column: 1 / -1; }
        .vw-field-label {
          font-size: 7.5pt;
          font-weight: 700;
          color: var(--vw-ink-muted);
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }
        .vw-field-value {
          font-size: 10pt;
          font-weight: 500;
          color: var(--vw-ink);
          background: ${VEEWASH_BRAND.pageBg};
          border: 1px solid ${VEEWASH_BRAND.borderSoft};
          border-radius: ${VEEWASH_BRAND.radiusSm};
          min-height: 0.26in;
          padding: 0.05in 0.08in;
        }
        .vw-pills {
          display: flex;
          flex-wrap: wrap;
          gap: 0.08in;
          margin-top: 0.06in;
        }
        .vw-pill {
          display: inline-flex;
          align-items: center;
          gap: 0.06in;
          font-size: 9pt;
          font-weight: 600;
          color: var(--vw-ink-muted);
          padding: 0.04in 0.1in;
          border-radius: 999px;
          border: 1px solid ${VEEWASH_BRAND.borderSoft};
          background: ${VEEWASH_BRAND.pageBg};
        }
        .vw-pill--on {
          color: ${VEEWASH_BRAND.primaryDark};
          border-color: ${VEEWASH_BRAND.primary};
          background: ${VEEWASH_BRAND.primaryLight};
        }
        .vw-pill-dot {
          width: 0.12in;
          height: 0.12in;
          border-radius: 50%;
          border: 2px solid ${VEEWASH_BRAND.borderSoft};
          flex-shrink: 0;
        }
        .vw-pill--on .vw-pill-dot {
          border-color: ${VEEWASH_BRAND.primary};
          background: ${VEEWASH_BRAND.primary};
          box-shadow: inset 0 0 0 2px #fff;
        }
        .vw-sub-label {
          font-size: 8pt;
          font-weight: 700;
          color: var(--vw-ink-soft, #64748b);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin: 0.1in 0 0.04in;
        }
        .vw-footer {
          margin-top: 0.14in;
          padding: 0.12in 0.16in;
          background: ${VEEWASH_BRAND.primaryDark};
          color: rgba(255,255,255,0.95);
          border-radius: ${VEEWASH_BRAND.radius};
          text-align: center;
          font-size: 8.5pt;
          line-height: 1.55;
        }
        .vw-footer strong { color: #fff; font-weight: 700; }
        @media print {
          @page {
            size: letter portrait;
            margin: 0.35in;
          }
          .vw-ddf-root {
            width: 100%;
            max-width: 100%;
            margin: 0;
            font-size: 8.5pt;
            line-height: 1.32;
          }
          .vw-ddf-hero {
            padding: 0.1in 0.14in 0.08in;
            margin-bottom: 0.07in;
          }
          .vw-ddf-logo {
            width: 0.55in;
            height: 0.55in;
            min-width: 0.55in;
          }
          .vw-ddf-company { font-size: 13pt; }
          .vw-ddf-tagline { font-size: 7.5pt; margin-top: 0.02in; }
          .vw-ddf-doc-title {
            font-size: 9.5pt;
            margin: 0.06in 0 0;
            padding-top: 0.06in;
          }
          .vw-ddf-gold-bar { margin-bottom: 0.06in; height: 2px; }
          .vw-card { margin-bottom: 0.05in; page-break-inside: avoid; }
          .vw-card-head { padding: 0.05in 0.1in; }
          .vw-card-num {
            width: 0.22in;
            height: 0.22in;
            font-size: 8pt;
          }
          .vw-card-title { font-size: 9pt; }
          .vw-card-body { padding: 0.06in 0.1in 0.07in; }
          .vw-grid { gap: 0.05in 0.08in; }
          .vw-field-label { font-size: 6.5pt; }
          .vw-field-value {
            font-size: 8.5pt;
            min-height: 0.2in;
            padding: 0.03in 0.06in;
          }
          .vw-pills { gap: 0.04in; margin-top: 0.03in; }
          .vw-pill { font-size: 7.5pt; padding: 0.02in 0.06in; }
          .vw-pill-dot { width: 0.1in; height: 0.1in; }
          .vw-sub-label { font-size: 7pt; margin: 0.05in 0 0.02in; }
          .vw-footer {
            margin-top: 0.06in;
            padding: 0.06in 0.1in;
            font-size: 7.5pt;
            line-height: 1.4;
            page-break-inside: avoid;
          }
        }
      `}</style>

      <header className="vw-ddf-hero">
        <ContractorPrintLogo prefill={p} className="vw-ddf-logo" />
        <div className="vw-ddf-hero-text">
          <div className="vw-ddf-company">{p.company_name || "VeeWash"}</div>
          <div className="vw-ddf-tagline">
            {contact.address} · {contact.phone}
          </div>
          <h1 className="vw-ddf-doc-title">Employee Information & Direct Deposit Authorization</h1>
        </div>
      </header>

      <div className="vw-ddf-gold-bar" aria-hidden />

      <Section num="1" title="Employee Information">
        <div className="vw-grid">
          <FieldRow label="First Name" value={p.first_name} />
          <FieldRow label="MI" value={p.middle_initial} />
          <FieldRow label="Last Name" value={p.last_name} />
          <FieldRow label="Address" value={p.address_line1} wide />
          <FieldRow label="City" value={p.city} />
          <FieldRow label="State" value={stateDisplay} />
          <FieldRow label="Zip Code" value={p.zip} />
          <FieldRow label="Social Security Number" value={p.ssn_display} />
          <FieldRow label="Date of Birth" value={p.date_of_birth} />
          <FieldRow label="Date of Hire" value={p.hire_date} />
          <FieldRow label="Email Address" value={p.email} wide />
        </div>
      </Section>

      <Section num="2" title="Employment Information">
        <div className="vw-sub-label">Pay type</div>
        <div className="vw-pills">
          <CheckPill label="Hourly" checked={payType === "hourly"} />
          <CheckPill label="Salary" checked={payType === "salary"} />
        </div>
        <div className="vw-grid vw-grid--2" style={{ marginTop: "0.1in" }}>
          <FieldRow label="Pay Amount ($)" value={p.pay_amount} />
          <FieldRow label="Tax Status" value={p.tax_status || "W-2"} />
        </div>
        <div className="vw-sub-label">Pay frequency</div>
        <div className="vw-pills">
          <CheckPill label="Weekly" checked={payFreq === "weekly"} />
          <CheckPill label="Bi-weekly" checked={payFreq === "biweekly" || payFreq === "bi-weekly"} />
          <CheckPill label="Semi-monthly" checked={payFreq === "semi-monthly" || payFreq === "semimonthly"} />
          <CheckPill label="Monthly" checked={payFreq === "monthly"} />
        </div>
        <div className="vw-sub-label">Federal filing status</div>
        <div className="vw-pills">
          <CheckPill label="Single" checked={filing === "single"} />
          <CheckPill label="Married" checked={filing === "married"} />
          <CheckPill
            label="Married – Higher single rate"
            checked={filing === "married_higher_single" || filing === "married_higher"}
          />
        </div>
      </Section>

      <Section num="3" title="Direct Deposit Information">
        <div className="vw-grid vw-grid--2">
          <FieldRow label="Bank Routing #" value={dd.bank_routing} />
          <FieldRow label="Bank Account #" value={dd.bank_account} />
        </div>
        <div className="vw-sub-label">Account type</div>
        <div className="vw-pills">
          <CheckPill label="Checking" checked={acctType === "checking"} />
          <CheckPill label="Saving" checked={acctType === "saving" || acctType === "savings"} />
        </div>
        <div className="vw-sub-label">Deposit amount</div>
        <div className="vw-pills">
          <CheckPill label="Full Amount" checked={dd.deposit_full !== false} />
        </div>
      </Section>

      <footer className="vw-footer">
        <strong>{p.company_name || "VeeWash"}</strong>
        <br />
        {contact.address} · {contact.phone} · {p.company_email || "payroll@veewash.com"}
      </footer>
    </div>
  );
}

/** SSN/TIN for print — same sources as I-9/W-4 prefill (i9.ssn, then payroll itin_ssn). */
export function resolveDirectDepositSsnDisplay(payroll, work) {
  const w = work && typeof work === "object" ? work : {};
  const i9 = w.i9 && typeof w.i9 === "object" ? w.i9 : {};
  const digits = normalizeTaxIdDigits(i9.ssn || "");
  if (digits.length === 9) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 5)}-${digits.slice(5)}`;
  }
  const last4 = String(payroll?.itin_ssn_last4 || "").trim();
  if (last4) return maskTaxIdLast4(last4);
  return "";
}

/** Build prefill object from merged payroll + HR API payloads. */
export function buildDirectDepositPrefill(payroll, hr, org) {
  const work = hr?.work_json && typeof hr.work_json === "object" ? hr.work_json : {};
  const dd = work.direct_deposit && typeof work.direct_deposit === "object" ? work.direct_deposit : {};
  const w4 = work.w4 && typeof work.w4 === "object" ? work.w4 : {};
  const addr = work.mailing || work;
  const addrLine =
    String(addr.address_line1 || addr.mailing_address_line1 || payroll?.address || "").trim() ||
    String(payroll?.address || "").split("\n")[0]?.trim();

  let filing = "single";
  const fs = String(w4.filing_status || w4.federal_filing_status || "").toLowerCase();
  if (fs.includes("married") && fs.includes("single")) filing = "married_higher_single";
  else if (fs.includes("married")) filing = "married";

  return {
    company_name: org?.employer_name || "VeeWash",
    company_email: org?.employer_email || "",
    first_name: payroll?.first_name || "",
    middle_initial: work.middle_initial || "",
    last_name: payroll?.last_name || "",
    address_line1: addrLine,
    city: addr.city || "",
    state: String(addr.state || "").trim().toUpperCase(),
    zip: addr.zip || addr.zip_code || "",
    ssn_display: resolveDirectDepositSsnDisplay(payroll, work),
    date_of_birth: hr?.date_of_birth || work.date_of_birth || "",
    hire_date: payroll?.hire_date || "",
    email: payroll?.email || "",
    pay_type: work.pay_type || "hourly",
    pay_amount: String(work.pay_amount || work.hourly_rate || "").trim() || "Full",
    tax_status: "W-2",
    pay_frequency: work.pay_frequency || "weekly",
    federal_filing_status: filing,
    direct_deposit: {
      bank_routing: dd.bank_routing || dd.routing_number || "",
      bank_account: dd.bank_account || dd.account_number || "",
      account_type: dd.account_type || "checking",
      deposit_full: dd.deposit_full !== false,
    },
  };
}
