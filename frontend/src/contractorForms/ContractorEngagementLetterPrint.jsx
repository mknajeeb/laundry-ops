/** Scaffold: Contractor Engagement and Payment Verification Letter */

export default function ContractorEngagementLetterPrint({ prefill, letter }) {
  const L = letter || {};
  const name = L.worker_name || prefill?.full_name || "______________________________";
  const cat =
    L.worker_category_label ||
    (L.worker_category === "temp" ? "Temp Contractor" : "1099 Contractor");
  return (
    <>
      <p className="cform-p">
        This letter confirms that, according to our records, <strong>{name}</strong> provided
        contractor services to VeeWash/Washpro
        {L.first_work_date || L.last_work_date
          ? ` from ${L.first_work_date || "________"} to ${L.last_work_date || "________"}`
          : ""}
        .
      </p>
      <p className="cform-p">
        <strong>Category:</strong> {cat}
        <br />
        <strong>Type of services:</strong> {L.services_description || "Laundry / contractor support"}
      </p>
      <p className="cform-p">
        Payments were made for contractor services based on approved work records. Average payments
        during the selected period were approximately{" "}
        <strong>${Number(L.avg_weekly_pay || 0).toFixed(2)}</strong> per week /{" "}
        <strong>${Number(L.avg_monthly_pay || 0).toFixed(2)}</strong> per month. Total paid in
        period: <strong>${Number(L.total_paid_period || 0).toFixed(2)}</strong>.
      </p>
      <p className="cform-p" style={{ fontSize: "9.5pt" }}>
        This letter is provided for record confirmation only and does not create or change any
        employment or contractor classification. This letter does not guarantee future work.
      </p>
      <div className="cform-sig-block">
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
