function FieldRow({ label, children }) {
  return (
    <div className="cform-field">
      <span className="cform-field-label">{label}</span>
      <span className="cform-field-value">{children}</span>
    </div>
  );
}

/** Biweekly contractor payment invoice — hours/rate/amounts due for the period. */
export default function ContractorPaymentInvoicePrint({ prefill, payment }) {
  const name = payment.contractor_name || prefill?.full_name || "";
  return (
    <>
      <p className="cform-p" style={{ color: "#475569", marginBottom: "0.14in" }}>
        This invoice summarizes approved contractor service for the pay period below.
        Contractor should review and sign; payment will be made per the agreed rate and method.
      </p>
      <FieldRow label="Contractor Name">{name || "______________________________"}</FieldRow>
      <FieldRow label="Invoice Period">
        From {payment.pay_period_start || "________"} To {payment.pay_period_end || "________"}
      </FieldRow>
      <FieldRow label="Invoice Date">{payment.invoice_date || "________"}</FieldRow>
      <table className="contractor-payment-table">
        <tbody>
          <tr>
            <td>Approved service hours</td>
            <td>{Number(payment.approved_service_hours || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Service rate</td>
            <td>${Number(payment.service_rate || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Service amount</td>
            <td>${Number(payment.service_amount || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Health &amp; Safety Credit hours, if any</td>
            <td>{Number(payment.health_safety_credit_hours || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Health &amp; Safety Credit amount, if any</td>
            <td>${Number(payment.health_safety_credit_amount || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>Adjustments, if any</td>
            <td>${Number(payment.adjustments || 0).toFixed(2)}</td>
          </tr>
          <tr>
            <td>
              <strong>Total amount due</strong>
            </td>
            <td>
              <strong>${Number(payment.total_payment || 0).toFixed(2)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <FieldRow label="Agreed payment method">
        {payment.payment_method || prefill?.payment_method || "________________"}
      </FieldRow>
      {payment.notes ? (
        <FieldRow label="Notes">
          <span style={{ whiteSpace: "pre-wrap" }}>{payment.notes}</span>
        </FieldRow>
      ) : null}
      <p className="cform-p" style={{ marginTop: "0.18in", fontSize: "9.5pt" }}>
        Contractor acknowledges this invoice reflects approved service time for the
        period above, unless Contractor notifies the Company of an error in writing.
      </p>
      <div className="cform-sig-block">
        <div>
          <strong>Contractor Signature</strong>
          <div className="cform-sig-line" />
          <strong>Date</strong>
          <div className="cform-sig-line" />
        </div>
        <div>
          <strong>Company Signature</strong>
          <div className="cform-sig-line" />
          <strong>Date</strong>
          <div className="cform-sig-line" />
        </div>
      </div>
    </>
  );
}
