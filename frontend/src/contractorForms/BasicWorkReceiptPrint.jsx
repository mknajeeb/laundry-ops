/** Short-term / one-time contractor work receipt — no onboarding or legal packet content. */

function line(val) {
  const s = val != null && String(val).trim() !== "" ? String(val).trim() : "";
  return s || "______________________________";
}

export default function BasicWorkReceiptPrint({ prefill, receipt }) {
  const r = receipt || {};
  const company = prefill?.company_name || "VeeWash / Washpro";
  const address =
    prefill?.company_address || "10438 Jamaica Avenue, Richmond Hill, NY 11418";

  return (
    <div className="contractor-print-root">
      <p style={{ fontWeight: 700, fontSize: "14pt", margin: "0 0 0.25rem" }}>
        {company}
      </p>
      <p style={{ margin: "0 0 1rem" }}>{address}</p>
      <h2 style={{ marginBottom: "0.75rem" }}>Basic Contractor Work Receipt</h2>
      <p style={{ fontSize: "10pt", marginBottom: "1rem" }}>
        Short-term / one-time work — confirms hours performed and payment received. Not an
        employee paystub or full contractor onboarding packet.
      </p>

      <table className="contractor-payment-table" style={{ marginBottom: "1rem" }}>
        <tbody>
          <tr>
            <td>
              <strong>Worker name</strong>
            </td>
            <td>{line(r.worker_name || prefill?.full_name)}</td>
          </tr>
          <tr>
            <td>
              <strong>Phone</strong>
            </td>
            <td>{line(r.phone || prefill?.phone)}</td>
          </tr>
          <tr>
            <td>
              <strong>Work period</strong>
            </td>
            <td>
              {line(r.work_period_start)} — {line(r.work_period_end)}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Work performed</strong>
            </td>
            <td style={{ textAlign: "left", whiteSpace: "pre-wrap" }}>
              {line(r.work_performed)}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Total hours worked</strong>
            </td>
            <td>
              {r.total_hours != null && r.total_hours !== ""
                ? Number(r.total_hours).toFixed(2)
                : line("")}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Rate</strong>
            </td>
            <td>
              {r.rate != null && r.rate !== ""
                ? `$${Number(r.rate).toFixed(2)}`
                : line("")}
            </td>
          </tr>
          <tr>
            <td>
              <strong>Total amount paid</strong>
            </td>
            <td>
              <strong>
                {r.total_amount_paid != null && r.total_amount_paid !== ""
                  ? `$${Number(r.total_amount_paid).toFixed(2)}`
                  : line("")}
              </strong>
            </td>
          </tr>
          <tr>
            <td>
              <strong>Payment method</strong>
            </td>
            <td>{line(r.payment_method || prefill?.payment_method)}</td>
          </tr>
          <tr>
            <td>
              <strong>Payment date</strong>
            </td>
            <td>{line(r.payment_date)}</td>
          </tr>
          <tr>
            <td>
              <strong>Payment reference / notes</strong>
            </td>
            <td style={{ textAlign: "left", whiteSpace: "pre-wrap" }}>
              {line(r.payment_reference_notes)}
            </td>
          </tr>
        </tbody>
      </table>

      <p style={{ fontSize: "10pt", marginTop: "1rem" }}>
        Worker confirms the hours and payment above, unless Worker notifies the Company of an
        error in writing.
      </p>

      <div className="sig-block">
        <div>
          <strong>Worker signature</strong>
          <div className="sig-line" />
          <strong>Date</strong>
          <div className="sig-line" />
        </div>
        <div>
          <strong>Company signature</strong>
          <div className="sig-line" />
          <strong>Date</strong>
          <div className="sig-line" />
        </div>
      </div>
    </div>
  );
}

export function emptyBasicReceipt(prefill) {
  return {
    worker_name: prefill?.full_name || "",
    phone: prefill?.phone || "",
    work_period_start: "",
    work_period_end: "",
    work_performed: "",
    total_hours: "",
    rate: prefill?.rate_per_hour != null ? String(prefill.rate_per_hour) : "",
    total_amount_paid: "",
    payment_method: prefill?.payment_method || "",
    payment_date: new Date().toISOString().slice(0, 10),
    payment_reference_notes: "",
  };
}

export function calcBasicReceiptTotal(hours, rate) {
  const h = Number(hours) || 0;
  const r = Number(rate) || 0;
  return Math.round(h * r * 100) / 100;
}
