import ContractorPrintShell from "../../contractorForms/ContractorPrintShell";
import {
  formatDisplayDate,
  resolveOfferLetterCompanyName,
} from "../../hr/offerLetter";
import {
  EMPLOYMENT_REFERENCE_DOCUMENT_TITLE,
  buildEmploymentPeriodText,
} from "../../hr/employmentReferenceLetter";

function display(val, fallback = "[not specified]") {
  const s = String(val ?? "").trim();
  return s || fallback;
}

function DetailRow({ label, value }) {
  return (
    <tr>
      <th>{label}</th>
      <td>{value}</td>
    </tr>
  );
}

/** Branded character and employment reference letter (print/PDF). */
export default function EmploymentReferencePrintDocument({ fields = {}, prefill = {} }) {
  const employee = display(fields.employee_name, "[Employee Name]");
  const position = display(fields.position);
  const letterDate = formatDisplayDate(fields.letter_date);
  const employmentStatus = display(fields.employment_status, "Current Employee");
  const location = display(fields.work_location);
  const reportingTo = display(fields.reporting_to, "Managing Director or designated supervisor");
  const signatory = display(fields.signatory_name, "[Signatory Name]");
  const signatoryTitle = display(fields.signatory_title, "Managing Director");
  const companyName = resolveOfferLetterCompanyName({ ...prefill, ...fields });
  const period = buildEmploymentPeriodText(fields);
  const characterStatement =
    String(fields.character_statement || "").trim() ||
    `During their time with ${companyName}, ${employee} has demonstrated professionalism, reliability, and a responsible approach to their duties.`;

  return (
    <ContractorPrintShell prefill={prefill} documentTitle={EMPLOYMENT_REFERENCE_DOCUMENT_TITLE} offerLetter>
      <div className="cform-offer-letter">
        <p className="cform-offer-date">{letterDate}</p>

        <p>To Whom It May Concern:</p>

        <p>
          This letter confirms that <strong>{employee}</strong> has been employed by{" "}
          <strong>{companyName}</strong> as <strong>{position}</strong> {period}.
        </p>

        <table className="cform-offer-table">
          <tbody>
            <DetailRow label="Position" value={position} />
            <DetailRow label="Employment Status" value={employmentStatus} />
            {fields.employment_start_date ? (
              <DetailRow
                label="Employment start date"
                value={formatDisplayDate(fields.employment_start_date)}
              />
            ) : null}
            <DetailRow
              label="Employment end date"
              value={
                String(fields.employment_end_date || "").trim()
                  ? formatDisplayDate(fields.employment_end_date)
                  : "Present"
              }
            />
            <DetailRow label="Work Location" value={location} />
            <DetailRow label="Reporting To" value={reportingTo} />
          </tbody>
        </table>

        {String(fields.employment_details || "").trim() ? (
          <div className="cform-offer-additional">
            {String(fields.employment_details)
              .trim()
              .split(/\n\s*\n/)
              .map((block) => block.trim())
              .filter(Boolean)
              .map((block, i) => (
                <p key={`duties-${i}`} style={{ whiteSpace: "pre-wrap" }}>
                  {block}
                </p>
              ))}
          </div>
        ) : null}

        <p style={{ whiteSpace: "pre-wrap" }}>{characterStatement}</p>

        {String(fields.custom_content || "").trim() ? (
          <div className="cform-offer-additional">
            {String(fields.custom_content)
              .trim()
              .split(/\n\s*\n/)
              .map((block) => block.trim())
              .filter(Boolean)
              .map((block, i) => (
                <p key={`custom-${i}`} style={{ whiteSpace: "pre-wrap" }}>
                  {block}
                </p>
              ))}
          </div>
        ) : null}

        <p>
          Please feel free to contact us should you require any additional information regarding
          their employment with {companyName}.
        </p>

        {String(fields.additional_terms || "").trim() ? (
          <div className="cform-offer-additional">
            <p>
              <strong>Additional terms / comments:</strong>
            </p>
            <p style={{ whiteSpace: "pre-wrap" }}>{String(fields.additional_terms).trim()}</p>
          </div>
        ) : null}

        <p>Sincerely,</p>

        <div className="cform-offer-signatures">
          <div className="cform-offer-sig-block">
            {signatory && signatory !== "[Signatory Name]" ? (
              <p className="cform-offer-digital-signature" aria-label={`Signed by ${signatory}`}>
                {signatory}
              </p>
            ) : (
              <div className="cform-sig-line" />
            )}
            <p>{signatory}</p>
            <p>{signatoryTitle}</p>
            <p>{companyName}</p>
          </div>
        </div>
      </div>
    </ContractorPrintShell>
  );
}
