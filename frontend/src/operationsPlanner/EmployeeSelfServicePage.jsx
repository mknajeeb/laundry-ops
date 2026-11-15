import { useEffect, useState } from "react";
import axios from "axios";
import { getWashproApiBase } from "../api";
import { loadPinHubSession } from "../utils/pinHubSession";
import { printDocumentHtml, scheduleCardSvg } from "./scheduleExport";
import "./operationsPlanner.css";

function client() {
  return axios.create({ baseURL: getWashproApiBase() });
}

export default function EmployeeSelfServicePage({ section }) {
  const session = loadPinHubSession();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [pin, setPin] = useState("");
  const [dob, setDob] = useState("");
  const [stepUp, setStepUp] = useState("");

  useEffect(() => {
    if (!session?.token || section === "paystubs") return undefined;
    let cancel = false;
    const path = section === "hours" ? "/api/public/attendance/pin-planner/hours" : "/api/public/attendance/pin-planner/schedule";
    client()
      .get(path, { headers: { "X-Pin-Hub-Token": session.token } })
      .then((response) => {
        if (!cancel) setData(response.data);
      })
      .catch((err) => {
        if (!cancel) setError(err.response?.data?.error || err.message);
      });
    return () => {
      cancel = true;
    };
  }, [section, session?.token]);

  async function verify(event) {
    event.preventDefault();
    setStepUp("");
    const response = await client().post(
      "/api/public/attendance/pin-planner/paystub/step-up",
      { pin, date_of_birth: dob, hub_token: session?.token },
      { headers: { "X-Pin-Hub-Token": session?.token }, validateStatus: () => true },
    );
    if (!response.data?.ok) {
      setError(response.data?.error || "Verification failed");
      return;
    }
    setStepUp(response.data.step_up_token);
    const list = await client().get("/api/public/attendance/pin-planner/paystubs", {
      headers: { "X-Pin-Hub-Token": session.token, "X-Paystub-Step-Up": response.data.step_up_token },
    });
    setData(list.data);
    setPin("");
  }

  async function openDocument(doc) {
    const response = await client().get(`/api/public/attendance/pin-planner/paystubs/${doc.batch_id}/${doc.line_id}`, {
      headers: { "X-Pin-Hub-Token": session.token, "X-Paystub-Step-Up": stepUp },
      responseType: "text",
    });
    const popup = window.open("", "_blank");
    if (!popup) return;
    popup.document.write(response.data);
    popup.document.close();
  }

  const schedule = data?.schedule;
  const title = section === "hours" ? "My worked hours" : section === "paystubs" ? "My paystubs" : "My schedule";

  return (
    <div className="ops-planner">
      <header>
        <div>
          <h1>{title}</h1>
          <p>Your records only</p>
        </div>
      </header>
      <div className="ops-main" style={{ gridTemplateColumns: "1fr" }}>
        {!session?.token ? <p>Enter your PIN on the employee menu first.</p> : null}
        {error ? <p className="ops-warn">{error}</p> : null}
        {data && data.visible === false ? <p>This section is not available on your PIN.</p> : null}
        {section === "schedule" && schedule ? (
          <section className="ops-board">
            {(schedule.entries || []).map((entry) => (
              <div key={entry.id || entry.start_time} className="lane">
                <strong>{entry.start_time}–{entry.end_time}</strong>
                <span>{entry.role}</span>
              </div>
            ))}
            <button
              type="button"
              onClick={() => {
                const html = printDocumentHtml({
                  title: "My schedule",
                  subtitle: schedule.week_start || "",
                  sections: [{
                    heading: "Shifts",
                    rows: (schedule.entries || []).map((entry) => ({
                      employee: "Me",
                      when: `${entry.start_time}–${entry.end_time}`,
                      detail: entry.role,
                    })),
                  }],
                });
                const popup = window.open("", "_blank");
                if (!popup) return;
                popup.document.write(html);
                popup.document.close();
                popup.print();
              }}
            >
              Print
            </button>
            <button
              type="button"
              onClick={() => {
                const svg = scheduleCardSvg({
                  title: "My schedule",
                  subtitle: schedule.week_start || "",
                  rows: (schedule.entries || []).map((entry) => ({ when: `${entry.start_time}–${entry.end_time}`, role: entry.role })),
                });
                const blob = new Blob([svg], { type: "image/svg+xml" });
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = url;
                link.download = "my-schedule.svg";
                link.click();
                URL.revokeObjectURL(url);
              }}
            >
              Save image
            </button>
          </section>
        ) : null}
        {section === "hours" && data?.visible ? (
          <section className="ops-board">
            <p>Recorded hours: {data.actual_hours}</p>
            <p>{data.scheduled_hours_note}</p>
            <p>{data.overtime_note || `Regular ${data.regular_hours} · overtime ${data.overtime_hours}`}</p>
          </section>
        ) : null}
        {section === "paystubs" ? (
          <section className="ops-board">
            {!stepUp ? (
              <form onSubmit={verify}>
                <p>Re-enter your PIN and the date of birth on your HR profile. This check stays in this tab and is not reused for the next person.</p>
                <input value={pin} onChange={(event) => setPin(event.target.value)} inputMode="numeric" autoComplete="off" placeholder="PIN" />
                <input value={dob} onChange={(event) => setDob(event.target.value)} type="date" />
                <button type="submit">Continue</button>
              </form>
            ) : (
              (data?.documents || []).map((doc) => (
                <button key={`${doc.batch_id}-${doc.line_id}`} type="button" onClick={() => openDocument(doc)}>
                  {doc.pay_period_start} – {doc.pay_period_end}
                </button>
              ))
            )}
            {stepUp && data?.documents?.length === 0 ? <p>No finalized W-2 paystub is on file.</p> : null}
          </section>
        ) : null}
      </div>
    </div>
  );
}
