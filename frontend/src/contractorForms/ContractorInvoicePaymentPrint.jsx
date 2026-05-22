/** Universal Contractor Invoice & Payment Receipt (print layout). */

function line(val) {
  const s = val != null && String(val).trim() !== "" ? String(val).trim() : "";
  return s || "______________________________";
}

function money(val) {
  if (val == null || val === "") return null;
  const n = Number(val);
  if (Number.isNaN(n)) return null;
  return `$${n.toFixed(2)}`;
}

function typeLabel(t) {
  if (t === "temp") return "Temporary / Short-Term Contractor";
  if (t === "one_time") return "One-Time Contractor";
  return "Regular Contractor";
}

export default function ContractorInvoicePaymentPrint({ record, prefill }) {
  const r = record || {};
  const isRegular = r.contractor_type === "regular";
  const priorYtd = Number(r.total_paid_ytd_prior) || 0;
  const amountPaid = Number(r.amount_paid) || 0;
  const ytdIncluding = Math.round((priorYtd + amountPaid) * 100) / 100;

  return (
    <>
      <p className="cform-p" style={{ color: "#475569", marginBottom: "0.12in" }}>
        <strong>Contractor type:</strong> {typeLabel(r.contractor_type)}
      </p>

      <h2 className="cform-section-title">Part 1 — Invoice / Work Summary</h2>
      <p className="cform-p" style={{ fontSize: "9.5pt", color: "#64748b" }}>
        Work summary for the pay period. Signature is not required for this section.
      </p>

      <table className="contractor-payment-table">
        <tbody>
          <tr>
            <td>
              <strong>Contractor / worker name</strong>
            </td>
            <td style={{ textAlign: "left" }}>{line(r.worker_name || prefill?.full_name)}</td>
          </tr>
          <tr>
            <td>
              <strong>Phone</strong>
            </td>
            <td style={{ textAlign: "left" }}>{line(r.worker_phone || prefill?.phone)}</td>
          </tr>
          <tr>
            <td>
              <strong>Email</strong>
            </td>
            <td style={{ textAlign: "left" }}>{line(r.worker_email || prefill?.email)}</td>
          </tr>
          <tr>
            <td>
              <strong>Work period</strong>
            </td>
            <td style={{ textAlign: "left" }}>
              {line(r.work_period_start)} — {line(r.work_period_end)}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Service performed</strong>
            </td>
            <td style={{ textAlign: "left", whiteSpace: "pre-wrap" }}>
              {line(r.work_performed)}
              {r.work_performed_notes ? (
                <>
                  <br />
                  <span style={{ color: "#64748b", fontSize: "9.5pt" }}>
                    Notes: {r.work_performed_notes}
                  </span>
                </>
              ) : null}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Total approved hours</strong>
            </td>
            <td>
              {r.approved_hours != null && r.approved_hours !== ""
                ? Number(r.approved_hours).toFixed(2)
                : line("")}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Service rate</strong>
            </td>
            <td>{money(r.service_rate) ?? line("")}</td>
          </tr>
          <tr>
            <td>
              <strong>Service amount</strong>
            </td>
            <td>{money(r.service_amount) ?? line("")}</td>
          </tr>
          {isRegular ? (
            <>
              <tr>
                <td>Health &amp; Safety Credit hours, if any</td>
                <td>
                  {Number(r.health_safety_credit_hours || 0).toFixed(2)}
                </td>
              </tr>
              <tr>
                <td>Health &amp; Safety Credit amount, if any</td>
                <td>{money(r.health_safety_credit_amount) ?? "$0.00"}</td>
              </tr>
            </>
          ) : null}
          <tr>
            <td>Adjustments, if any</td>
            <td>{money(r.adjustment_amount) ?? "$0.00"}</td>
          </tr>
          <tr>
            <td>
              <strong>Total amount due</strong>
            </td>
            <td>
              <strong>{money(r.total_amount_due) ?? line("")}</strong>
            </td>
          </tr>
          <tr>
            <td>Total paid this year (before this payment)</td>
            <td>{money(priorYtd) ?? "$0.00"}</td>
          </tr>
          <tr>
            <td>Total paid this year (including this payment)</td>
            <td>
              <strong>{money(ytdIncluding) ?? line("")}</strong>
            </td>
          </tr>
        </tbody>
      </table>

      <h2 className="cform-section-title" style={{ marginTop: "0.28in" }}>
        Part 2 — Payment Receipt
      </h2>
      <p className="cform-p" style={{ fontSize: "9.5pt" }}>
        Worker/Contractor confirms that the work listed above was completed and that payment
        listed below was received. This receipt confirms payment only and does not waive any legal
        rights. This form does not guarantee future work.
      </p>

      <table className="contractor-payment-table">
        <tbody>
          <tr>
            <td>
              <strong>Amount paid</strong>
            </td>
            <td>
              <strong>{money(r.amount_paid) ?? line("")}</strong>
            </td>
          </tr>
          <tr>
            <td>
              <strong>Payment method</strong>
            </td>
            <td style={{ textAlign: "left" }}>{line(r.payment_method)}</td>
          </tr>
          <tr>
            <td>
              <strong>Payment reference</strong>
            </td>
            <td style={{ textAlign: "left" }}>{line(r.payment_reference)}</td>
          </tr>
          <tr>
            <td>
              <strong>Payment date</strong>
            </td>
            <td style={{ textAlign: "left" }}>{line(r.payment_date)}</td>
          </tr>
        </tbody>
      </table>

      <div className="cform-sig-block">
        <div>
          <strong>Contractor / worker signature</strong>
          <div className="cform-sig-line" />
          <strong>Date</strong>
          <div className="cform-sig-line" />
        </div>
        <div>
          <strong>Company signature</strong>
          <div className="cform-sig-line" />
          <strong>Date</strong>
          <div className="cform-sig-line" />
        </div>
      </div>
    </>
  );
}

export function emptyPaymentRecord(prefill = {}, contractorType = "regular") {
  const today = new Date().toISOString().slice(0, 10);
  return {
    contractor_type: contractorType,
    worker_name: prefill?.full_name || "",
    worker_phone: prefill?.phone || "",
    worker_email: prefill?.email || "",
    work_period_start: "",
    work_period_end: "",
    work_performed_preset: "",
    work_performed: "",
    work_performed_notes: "",
    approved_hours: "",
    service_rate: prefill?.rate_per_hour != null ? String(prefill.rate_per_hour) : "",
    service_amount: 0,
    health_safety_credit_hours: "",
    health_safety_credit_amount: 0,
    adjustment_amount: "",
    total_amount_due: 0,
    amount_paid: "",
    payment_method: prefill?.payment_method || "",
    payment_reference: "",
    payment_date: today,
    invoice_date: today,
    total_paid_ytd_prior: "0",
    notes: "",
    source_type: "manual",
    status: "paid",
  };
}

export function calcServiceAmount(hours, rate) {
  const h = Number(hours) || 0;
  const r = Number(rate) || 0;
  return Math.round(h * r * 100) / 100;
}
