/** Universal Contractor Invoice & Payment Receipt (print layout). */

import { formatUsPhoneDisplay } from "../utils/validation";

function hasValue(val) {
  return val != null && String(val).trim() !== "";
}

function pickText(...vals) {
  for (const v of vals) {
    if (hasValue(v)) return String(v).trim();
  }
  return null;
}

function pickPhone(...vals) {
  for (const v of vals) {
    const formatted = formatUsPhoneDisplay(v);
    if (formatted) return formatted;
  }
  return null;
}

function formatMoney(val) {
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

function splitSupervisorNameTitle(rawName, rawTitle) {
  const title = pickText(rawTitle);
  const nameRaw = pickText(rawName);
  if (!nameRaw) return { name: null, title };
  if (title) return { name: nameRaw, title };
  const comma = nameRaw.indexOf(",");
  if (comma > 0) {
    return {
      name: nameRaw.slice(0, comma).trim(),
      title: nameRaw.slice(comma + 1).trim() || null,
    };
  }
  return { name: nameRaw, title: null };
}

function PrintTable({ rows }) {
  const visible = rows.filter((row) => row.value != null && row.value !== "");
  if (!visible.length) return null;
  return (
    <table className="contractor-payment-table">
      <tbody>
        {visible.map((row) => (
          <tr key={row.key}>
            <td>
              {row.strongLabel ? <strong>{row.label}</strong> : row.label}
            </td>
            <td style={{ textAlign: row.left ? "left" : undefined }}>
              {row.strongValue ? <strong>{row.value}</strong> : row.value}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ContractorInvoicePaymentPrint({ record, prefill }) {
  const r = record || {};
  const isRegular = r.contractor_type === "regular";
  const priorYtd = Number(r.total_paid_ytd_prior) || 0;
  const amountPaid = Number(r.amount_paid) || 0;
  const ytdIncluding = Math.round((priorYtd + amountPaid) * 100) / 100;

  const workPeriodStart = pickText(r.work_period_start);
  const workPeriodEnd = pickText(r.work_period_end);
  let workPeriod = null;
  if (workPeriodStart && workPeriodEnd) workPeriod = `${workPeriodStart} — ${workPeriodEnd}`;
  else if (workPeriodStart) workPeriod = workPeriodStart;
  else if (workPeriodEnd) workPeriod = workPeriodEnd;

  const hsHours = Number(r.health_safety_credit_hours) || 0;
  const hsAmount = Number(r.health_safety_credit_amount) || 0;
  const adjustments = Number(r.adjustment_amount) || 0;

  const part1Rows = [
    {
      key: "name",
      label: "Contractor / worker name",
      value: pickText(r.worker_name, prefill?.full_name),
      strongLabel: true,
      left: true,
    },
    { key: "phone", label: "Phone", value: pickPhone(r.worker_phone, prefill?.phone), left: true },
    { key: "email", label: "Email", value: pickText(r.worker_email, prefill?.email), left: true },
    { key: "period", label: "Work period", value: workPeriod, left: true },
    {
      key: "hours",
      label: "Total approved hours",
      value: hasValue(r.approved_hours) ? Number(r.approved_hours).toFixed(2) : null,
    },
    {
      key: "rate",
      label: "Service rate",
      value: formatMoney(r.service_rate),
    },
    {
      key: "service_amount",
      label: "Service amount",
      value: formatMoney(r.service_amount),
    },
  ];

  if (isRegular && hsHours > 0) {
    part1Rows.push({
      key: "hs_hours",
      label: "Health & Safety Credit hours, if any",
      value: hsHours.toFixed(2),
    });
  }
  if (isRegular && hsAmount > 0) {
    part1Rows.push({
      key: "hs_amount",
      label: "Health & Safety Credit amount, if any",
      value: formatMoney(hsAmount),
    });
  }
  if (adjustments !== 0) {
    part1Rows.push({
      key: "adjustments",
      label: "Adjustments, if any",
      value: formatMoney(adjustments),
    });
  }

  part1Rows.push(
    {
      key: "total_due",
      label: "Total amount due",
      value: formatMoney(r.total_amount_due),
      strongLabel: true,
      strongValue: true,
    },
    {
      key: "ytd_prior",
      label: "Total paid this year (before this payment)",
      value: priorYtd > 0 ? formatMoney(priorYtd) : null,
    },
    {
      key: "ytd_including",
      label: "Total paid this year (including this payment)",
      value: formatMoney(ytdIncluding),
      strongValue: true,
    },
  );

  const part2Rows = [
    {
      key: "amount_paid",
      label: "Amount paid",
      value: formatMoney(r.amount_paid),
      strongLabel: true,
      strongValue: true,
    },
    {
      key: "method",
      label: "Payment method",
      value: pickText(r.payment_method),
      left: true,
    },
  ];

  if (r.print_include_payment_reference !== false && hasValue(r.payment_reference)) {
    part2Rows.push({
      key: "reference",
      label: "Payment reference",
      value: pickText(r.payment_reference),
      left: true,
    });
  }

  part2Rows.push({
    key: "payment_date",
    label: "Payment date",
    value: pickText(r.payment_date),
    left: true,
    strongLabel: true,
  });

  const supervisor = splitSupervisorNameTitle(
    pickText(r.company_supervisor_name, prefill?.company_supervisor_name, prefill?.company_representative),
    pickText(r.company_supervisor_title, prefill?.company_supervisor_title),
  );
  const workerName = pickText(r.worker_name, prefill?.full_name);

  return (
    <>
      <p className="cform-p" style={{ color: "#475569", marginBottom: "0.12in" }}>
        <strong>Contractor type:</strong> {typeLabel(r.contractor_type)}
      </p>

      <h2 className="cform-section-title">Part 1 — Invoice / Work Summary</h2>
      <p className="cform-p" style={{ fontSize: "9.5pt", color: "#64748b" }}>
        Work summary for the pay period. Signature is not required for this section.
      </p>

      <PrintTable rows={part1Rows} />

      <h2 className="cform-section-title" style={{ marginTop: "0.28in" }}>
        Part 2 — Payment Receipt
      </h2>
      <p className="cform-p" style={{ fontSize: "9.5pt" }}>
        Worker/Contractor confirms that the work listed above was completed and that payment
        listed below was received. This receipt confirms payment only and does not waive any legal
        rights. This form does not guarantee future work.
      </p>

      <PrintTable rows={part2Rows} />

      <div className="cform-sig-block">
        <div>
          <strong>Contractor / worker signature</strong>
          {workerName ? (
            <p className="cform-sig-printed-name">
              <strong>Name:</strong> {workerName}
            </p>
          ) : null}
          <div className="cform-sig-line" />
          <strong>Date</strong>
          <div className="cform-sig-line" />
        </div>
        <div>
          <strong>Company signature</strong>
          {supervisor.name || supervisor.title ? (
            <div className="cform-sig-printed-name">
              {supervisor.name ? (
                <p className="cform-p" style={{ margin: "0.06in 0 0", fontSize: "10pt" }}>
                  <strong>Name:</strong> {supervisor.name}
                </p>
              ) : null}
              {supervisor.title ? (
                <p className="cform-p" style={{ margin: "0.04in 0 0", fontSize: "10pt" }}>
                  <strong>Title:</strong> {supervisor.title}
                </p>
              ) : null}
            </div>
          ) : null}
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
    amount_paid_manual: false,
    print_include_payment_reference: true,
    company_supervisor_name: prefill?.company_supervisor_name || "",
    company_supervisor_title: prefill?.company_supervisor_title || "",
    notes: "",
    source_type: "manual",
    status: "paid",
  };
}

export function splitSupervisorFields(full) {
  const raw = String(full || "").trim();
  if (!raw) return { company_supervisor_name: "", company_supervisor_title: "" };
  const comma = raw.indexOf(",");
  if (comma > 0) {
    return {
      company_supervisor_name: raw.slice(0, comma).trim(),
      company_supervisor_title: raw.slice(comma + 1).trim(),
    };
  }
  return { company_supervisor_name: raw, company_supervisor_title: "" };
}

export function calcServiceAmount(hours, rate) {
  const h = Number(hours) || 0;
  const r = Number(rate) || 0;
  return Math.round(h * r * 100) / 100;
}
