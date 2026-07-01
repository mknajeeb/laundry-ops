import ContractorPrintShell from "../../contractorForms/ContractorPrintShell";
import {
  formatDisplayDate,
  resolveOfferLetterCompanyName,
} from "../../hr/offerLetter";
import { POSITION_CONFIRMATION_DOCUMENT_TITLE } from "../../hr/positionConfirmationLetter";

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

/** Branded position confirmation letter after probation (print/PDF). */
export default function PositionConfirmationPrintDocument({ fields = {}, prefill = {} }) {
  const employee = display(fields.employee_name, "[Employee Name]");
  const position = display(fields.position);
  const letterDate = formatDisplayDate(fields.letter_date);
  const effectiveDate = formatDisplayDate(fields.effective_date);
  const employmentStatus = display(fields.employment_status, "Regular Employee");
  const location = display(fields.work_location);
  const reportingTo = display(fields.reporting_to, "Managing Director or designated supervisor");
  const signatory = display(fields.signatory_name, "[Signatory Name]");
  const signatoryTitle = display(fields.signatory_title, "Managing Director");
  const companyName = resolveOfferLetterCompanyName({ ...prefill, ...fields });
  const firstName = employee.split(" ")[0] || employee;

  return (
    <ContractorPrintShell prefill={prefill} documentTitle={POSITION_CONFIRMATION_DOCUMENT_TITLE} offerLetter>
      <div className="cform-offer-letter">
        <p className="cform-offer-date">{letterDate}</p>

        <div className="cform-offer-recipient">
          <p>{employee}</p>
          {fields.employee_address ? <p style={{ whiteSpace: "pre-wrap" }}>{fields.employee_address}</p> : null}
        </div>

        <p className="cform-offer-re">
          <strong>Re:</strong> Confirmation of Employment – {position}
        </p>

        <p>Dear {firstName},</p>

        <p>
          We are pleased to confirm that, effective <strong>{effectiveDate}</strong>, you have successfully
          completed your probationary period and are now confirmed as a{" "}
          <strong>{employmentStatus}</strong> of {companyName} in the position of{" "}
          <strong>{position}</strong>.
        </p>

        <p>
          During your probationary period, you demonstrated professionalism, dedication, and a strong
          commitment to supporting {companyName}&apos;s operational excellence. We appreciate your
          contributions and are pleased to have you as a permanent member of our team.
        </p>

        <p>Your employment is confirmed under the following terms:</p>

        <table className="cform-offer-table">
          <tbody>
            <DetailRow label="Position" value={position} />
            <DetailRow label="Employment Status" value={employmentStatus} />
            <DetailRow label="Effective Date of Confirmation" value={effectiveDate} />
            <DetailRow label="Work Location" value={location} />
            <DetailRow label="Reporting To" value={reportingTo} />
          </tbody>
        </table>

        <p>
          All other terms and conditions of your employment remain unchanged. Your employment will
          continue on an at-will basis in accordance with applicable law and the Company&apos;s policies.
        </p>

        <p>
          Congratulations on successfully completing your probationary period. We look forward to your
          continued contributions and wish you every success as you grow with {companyName}.
        </p>

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
