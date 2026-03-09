import { useEffect, useState } from "react";
import { getOrders } from "../api";
import { useSearchParams } from "react-router-dom";

function OrdersPage() {
  const [orders, setOrders] = useState([]);
  const [search, setSearch] = useState("");
  const [service, setService] = useState("");
  const [delivery, setDelivery] = useState("");

  const [params] = useSearchParams();

  useEffect(() => {
    loadOrders();
  }, []);

  const loadOrders = () => {
    getOrders()
      .then((res) => setOrders(res.data))
      .catch((err) => console.error(err));
  };

  useEffect(() => {
    const s = params.get("service");
    const r = params.get("rush");

    if (s) setService(s);
    if (r) setDelivery(r);
  }, [params]);

  const filtered = orders
    .filter((o) => {
      if (service === "WF") return o.service_type === "WF";
      if (service === "HD") return o.service_type === "HD";
      return true;
    })
    .filter((o) => {
      if (delivery === "RUSH") return o.rush_type === "RUSH";
      if (delivery === "NON-RUSH") return o.rush_type === "NON-RUSH";
      return true;
    })
    .filter((o) => {
      if (!search) return true;
      return o.name_clean.toLowerCase().startsWith(search.toLowerCase());
    })
    .sort((a, b) => a.name_clean.localeCompare(b.name_clean));

  const totalWeight = filtered
    .reduce((sum, o) => sum + (parseFloat(o.weight_num) || 0), 0)
    .toFixed(2);

  const batchTitle =
    service && delivery ? `${service} - ${delivery}` : "ALL ORDERS";

  const batchDate = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "America/New_York",
  });

  return (
    <div className="orders-container">
      <div className="orders-header">
        <div>
          <h1 className="orders-title">Laundry Orders</h1>

          <div style={{ marginTop: 10 }}>
            <strong>Service</strong>

            <label style={{ marginLeft: 15 }}>
              <input
                type="checkbox"
                checked={service === "WF"}
                onChange={() => setService(service === "WF" ? "" : "WF")}
              />
              WF
            </label>

            <label style={{ marginLeft: 10 }}>
              <input
                type="checkbox"
                checked={service === "HD"}
                onChange={() => setService(service === "HD" ? "" : "HD")}
              />
              HD
            </label>
          </div>

          <div style={{ marginTop: 6 }}>
            <strong>Delivery</strong>

            <label style={{ marginLeft: 15 }}>
              <input
                type="checkbox"
                checked={delivery === "RUSH"}
                onChange={() => setDelivery(delivery === "RUSH" ? "" : "RUSH")}
              />
              Rush
            </label>

            <label style={{ marginLeft: 10 }}>
              <input
                type="checkbox"
                checked={delivery === "NON-RUSH"}
                onChange={() =>
                  setDelivery(delivery === "NON-RUSH" ? "" : "NON-RUSH")
                }
              />
              Non Rush
            </label>
          </div>
        </div>

        <div className="orders-widget">
          <div className="widget-box">
            <div className="widget-label">Orders</div>
            <div className="widget-value">{filtered.length}</div>
          </div>

          <div className="widget-box">
            <div className="widget-label">Weight</div>
            <div className="widget-value">{totalWeight} lbs</div>
          </div>
        </div>
      </div>

      <div className="alphabet">
        {"ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map((letter) => (
          <button key={letter} onClick={() => setSearch(letter)}>
            {letter}
          </button>
        ))}

        <button onClick={() => setSearch("")}>Clear</button>
      </div>

      <input
        className="search-box"
        placeholder="Search name..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="print-bar">
        <button
          onClick={() => window.print()}
          style={{
            padding: "8px 14px",
            background: "#2563eb",
            color: "white",
            border: "none",
            borderRadius: "6px",
            cursor: "pointer",
          }}
        >
          Print Sheet
        </button>
      </div>

      <table className="orders-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Date</th>
            <th>Name</th>
            <th>Weight</th>
            <th>Service</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>

        <tbody>
          {filtered.map((o) => (
            <tr key={o.id}>
              <td>{o.id}</td>
              <td>{o.date_clean}</td>
              <td>{o.name_clean}</td>
              <td>{o.weight_num || "-"}</td>
              <td>{o.service_type}</td>
              <td>{o.status}</td>

              <td>
                <button>Edit</button>
                <button>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="print-area">
        <div className="print-header">
          <div className="print-logos">
            <img src="/washpro.png" className="print-logo" />
            <img src="/rinse.png" className="print-logo" />
          </div>

          <h1 className="print-title">{batchTitle}</h1>

          <div className="print-subtitle">Batch Date: {batchDate}</div>
          <div className="print-subtitle">Total Orders: {filtered.length}</div>
        </div>

        <div className="print-grid">
          <div>
            {filtered.slice(0, Math.ceil(filtered.length / 2)).map((o, i) => (
              <div key={o.id} className="print-row">
                <span className="num">{i + 1}</span>
                <span className="check">□</span>
                <span className="name">{o.name_clean}</span>
                <span className="weight">
                  {o.service_type === "HD"
                    ? o.weight_num
                    : o.weight_num?.toFixed(2)}
                </span>
              </div>
            ))}
          </div>

          <div>
            {filtered.slice(Math.ceil(filtered.length / 2)).map((o, i) => (
              <div key={o.id} className="print-row">
                <span className="num">
                  {i + 1 + Math.ceil(filtered.length / 2)}
                </span>
                <span className="check">□</span>
                <span className="name">{o.name_clean}</span>
                <span className="weight">
                  {o.service_type === "HD"
                    ? o.weight_num
                    : o.weight_num?.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default OrdersPage;