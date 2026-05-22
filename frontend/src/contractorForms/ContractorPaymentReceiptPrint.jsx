function FieldRow({ label, children }) {
  return (
    <div className="cform-field">
      <span className="cform-field-label">{label}</span>
      <span className="cform-field-value">{children}</span>
    </div>
  );
}

/** Payment receipt — confirms payment was made (not the line-item invoice). */
export default function ContractorPaymentReceiptPrint({ prefill, receipt }) {
  const r = receipt || {};
  const name = r.contractor_name || prefill?.full_name || "";
  return (
    <>
      <p className="cform-p" style={{ color: "#475569", marginBottom: "0.14in" }}>
        This receipt confirms that contractor payment was made for the period below.
        It is not an employee paystub or wage statement.
      </p>
      <FieldRow label="Contractor Name">{name || "______________________________"}</FieldRow>
      <FieldRow label="Pay period covered">
        From {r.pay_period_start || "________"} To {r.pay_period_end || "________"}
      </FieldRow>
      <FieldRow label="Invoice / reference date">{r.invoice_date || "________"}</FieldRow>
      <table className="contractor-payment-table">
        <tbody>
          <tr>
            <td>Total hours paid (if applicable)</td>
            <td>
              {r.approved_service_hours != null && r.approved_service_hours !== ""
                ? Number(r.approved_service_hours).toFixed(2)
                : "—"}
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
                  : "________________"}
              </strong>
            </td>
          </tr>
          <tr>
            <td>Payment date</td>
            <td>{r.payment_date || "________________"}</td>
          </tr>
          <tr>
            <td>Payment method</td>
            <td>{r.payment_method || "________________"}</td>
          </tr>
          <tr>
            <td>Payment reference</td>
            <td>{r.payment_reference || "________________"}</td>
          </tr>
        </tbody>
      </table>
      {r.notes ? (
        <FieldRow label="Notes">
          <span style={{ whiteSpace: "pre-wrap" }}>{r.notes}</span>
        </FieldRow>
      ) : null}
      <p className="cform-p" style={{ marginTop: "0.18in", fontSize: "9.5pt" }}>
        Contractor acknowledges receipt of the payment above, unless Contractor notifies
        the Company of an error in writing.
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

export function receiptFromInvoice(payment, prefill) {
  return {
    contractor_name: payment.contractor_name || prefill?.full_name || "",
    pay_period_start: payment.pay_period_start || "",
    pay_period_end: payment.pay_period_end || "",
    invoice_date: payment.invoice_date || "",
    approved_service_hours: payment.approved_service_hours,
    total_amount_paid: payment.total_payment,
    payment_date: payment.payment_date || new Date().toISOString().slice(0, 10),
    payment_method: payment.payment_method || prefill?.payment_method || "",
    payment_reference: payment.payment_reference || "",
    notes: payment.notes || "",
  };
}
