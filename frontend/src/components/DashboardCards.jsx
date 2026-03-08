import { useNavigate } from "react-router-dom";

export default function DashboardCards({ stats }) {

  const navigate = useNavigate();

  const go = (service, rush) => {

    let url = "/orders";

    if (service) url += `?service=${service}`;
    if (rush) url += `${service ? "&" : "?"}rush=${rush}`;

    navigate(url);
  };

  return (

    <div className="dashboard">

      <h2 className="section-title">Orders</h2>

      <div className="card-row">

        <div
          className="card clickable"
          onClick={() => go()}
        >
          <h1>{stats.total_orders}</h1>
          <p>All Orders</p>
        </div>

      </div>


      <h2 className="section-title">Wash & Fold</h2>

      <div className="card-row">

        <div
          className="card clickable"
          onClick={() => go("WF")}
        >
          <h1>{stats.wf_total}</h1>
          <p>WF Total</p>
        </div>

        <div
          className="card rush clickable"
          onClick={() => go("WF","RUSH")}
        >
          <h1>{stats.wf_rush}</h1>
          <p>WF Rush</p>
        </div>

        <div
          className="card clickable"
          onClick={() => go("WF","NON-RUSH")}
        >
          <h1>{stats.wf_non_rush}</h1>
          <p>WF Non Rush</p>
        </div>

      </div>


      <h2 className="section-title">Hang Dry</h2>

      <div className="card-row">

        <div
          className="card clickable"
          onClick={() => go("HD")}
        >
          <h1>{stats.hd_total}</h1>
          <p>HD Total</p>
        </div>

        <div
          className="card rush clickable"
          onClick={() => go("HD","RUSH")}
        >
          <h1>{stats.hd_rush}</h1>
          <p>HD Rush</p>
        </div>

        <div
          className="card clickable"
          onClick={() => go("HD","NON-RUSH")}
        >
          <h1>{stats.hd_non_rush}</h1>
          <p>HD Non Rush</p>
        </div>

      </div>

    </div>

  );
}