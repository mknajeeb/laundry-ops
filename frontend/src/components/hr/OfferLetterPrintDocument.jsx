import ContractorPrintShell from "../../contractorForms/ContractorPrintShell";
import {
  formatDisplayDate,
  OFFER_LETTER_CONTACT_EMAIL,
  offerLetterDocumentTitle,
} from "../../hr/offerLetter";

function display(val, fallback = "[not specified]") {
  const s = String(val ?? "").trim();
  return s || fallback;
}

function DetailRow({ label, value, multiline = false }) {
  return (
    <tr>
      <th>{label}</th>
      <td style={multiline ? { whiteSpace: "pre-wrap" } : undefined}>{value}</td>
    </tr>
  );
}

/** Branded offer letter for W-2 employees or 1099 contractors (print/PDF). */
export default function OfferLetterPrintDocument({ fields = {}, prefill = {} }) {
  const isContractor = Boolean(fields.is_contractor);
  const docTitle = offerLetterDocumentTitle(isContractor);
  const candidate = display(fields.candidate_name, "[Candidate Name]");
  const position = display(fields.position);
  const positionDetails = String(fields.position_details || "").trim();
  const contactEmail = String(fields.contact_email || OFFER_LETTER_CONTACT_EMAIL).trim()
    || OFFER_LETTER_CONTACT_EMAIL;
  const startDate = formatDisplayDate(fields.start_date);
  const compensation = display(fields.compensation);
  const location = display(fields.work_location);
  const schedule = display(fields.schedule);
  const payFrequency = display(fields.pay_frequency);
  const manager = display(fields.manager_name, "[Manager Name]");
  const managerTitle = display(fields.manager_title, "[Title]");
  const offerDate = formatDisplayDate(fields.offer_date);
  const responseDeadline = fields.response_deadline
    ? formatDisplayDate(fields.response_deadline)
    : null;
  const additionalTerms = String(fields.additional_terms || "").trim();

  return (
    <ContractorPrintShell prefill={prefill} documentTitle={docTitle}>
      <div className="cform-offer-letter">
        <p className="cform-offer-date">{offerDate}</p>

        <div className="cform-offer-recipient">
          <p>{candidate}</p>
          {fields.candidate_address ? <p>{fields.candidate_address}</p> : null}
        </div>

        <p className="cform-offer-re">
          <strong>Re:</strong> {docTitle} — {position}
        </p>

        <p>Dear {candidate.split(" ")[0] || candidate},</p>

        {isContractor ? (
          <>
            <p>
              VeeWash / WashPro is pleased to offer you an opportunity to perform services as an
              independent contractor in the position of <strong>{position}</strong>, subject to the
              terms below and the Independent Contractor Agreement and related standards documents
              you will receive for review and signature.
            </p>
            <p>
              This offer is for project-based laundry production and related operational services.
              Work is offered by assignment; acceptance of each assignment is at your discretion
              unless otherwise agreed in writing.
            </p>
          </>
        ) : (
          <>
            <p>
              VeeWash / WashPro is pleased to offer you employment in the position of{" "}
              <strong>{position}</strong> on an at-will basis, subject to the terms below and the
              policies described in the Employee Handbook and Performance Standards Addendum.
            </p>
            <p>
              We believe your experience and work ethic will be a strong fit for our production team.
              This letter summarizes the principal terms of our offer; it is not a contract of
              employment for a fixed term.
            </p>
          </>
        )}

        <table className="cform-offer-table">
          <tbody>
            <DetailRow label="Position" value={position} />
            {positionDetails ? (
              <DetailRow label="Position details" value={positionDetails} multiline />
            ) : null}
            <DetailRow label="Start date" value={startDate} />
            <DetailRow label="Work location" value={location} />
            <DetailRow label="Schedule" value={schedule} />
            <DetailRow
              label={isContractor ? "Service rate" : "Hourly rate"}
              value={compensation}
            />
            <DetailRow label="Pay frequency" value={payFrequency} />
          </tbody>
        </table>

        {isContractor ? (
          <p>
            Payment is issued for approved services completed in accordance with company standards.
            You are responsible for your own taxes, insurance, and business expenses unless otherwise
            stated in the contractor agreement.
          </p>
        ) : (
          <p>
            You will be paid in accordance with company payroll practices and applicable wage laws.
            Benefits, if any, will be described separately when applicable. Employment remains
            at-will and may be ended by either party at any time, with or without cause or notice,
            except where prohibited by law.
          </p>
        )}

        <p>
          Your start is contingent upon satisfactory completion of required onboarding, including
          identity verification{isContractor ? ", contractor agreement execution," : ", I-9 verification,"}{" "}
          background screening where applicable, and acknowledgment of company standards documents.
        </p>

        {responseDeadline ? (
          <p>
            Please confirm your acceptance of this offer by <strong>{responseDeadline}</strong> by
            emailing <strong>{contactEmail}</strong>
            {manager && manager !== "[Manager Name]" ? (
              <>
                {" "}
                or contacting {manager}
                {fields.manager_title ? `, ${managerTitle},` : ""}
              </>
            ) : null}
            .
          </p>
        ) : (
          <p>
            Please confirm your acceptance of this offer by emailing <strong>{contactEmail}</strong>
            {manager && manager !== "[Manager Name]" ? (
              <>
                {" "}
                or contacting {manager}
                {fields.manager_title ? `, ${managerTitle},` : ""}
              </>
            ) : null}
            .
          </p>
        )}

        {additionalTerms ? (
          <div className="cform-offer-additional">
            <p>
              <strong>Additional terms:</strong>
            </p>
            <p style={{ whiteSpace: "pre-wrap" }}>{additionalTerms}</p>
          </div>
        ) : null}

        <p>We look forward to working with you.</p>

        <div className="cform-offer-signatures">
          <div className="cform-offer-sig-block">
            <div className="cform-sig-line" />
            <p>{manager}</p>
            <p>{managerTitle}</p>
            <p>VeeWash / WashPro</p>
          </div>
          <div className="cform-offer-sig-block">
            <div className="cform-sig-line" />
            <p>Accepted by: {candidate}</p>
            <p>Date: ____________________</p>
          </div>
        </div>
      </div>
    </ContractorPrintShell>
  );
}
