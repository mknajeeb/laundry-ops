import { useEffect, useState } from "react";
import axios from "axios";

const API = "http://localhost:8000";

function DashboardPage() {

  const [stats, setStats] = useState(null);

  useEffect(() => {
    axios.get(`${API}/dashboard`)
      .then(res => setStats(res.data))
      .catch(err => console.error(err));
  }, []);

  if (!stats) return <div>Loading dashboard...</div>;

  return (
    <div className="dashboard">

      <h1>Operations Dashboard</h1>

      <div className="cards">

        <div className="card">
          <h3>Total Orders</h3>
          <p>{stats.total_orders}</p>
        </div>

        <div className="card">
          <h3>WF Rush</h3>
          <p>{stats.wf_rush}</p>
        </div>

        <div className="card">
          <h3>WF Non Rush</h3>
          <p>{stats.wf_non_rush}</p>
        </div>

        <div className="card">
          <h3>HD Rush</h3>
          <p>{stats.hd_rush}</p>
        </div>

        <div className="card">
          <h3>HD Non Rush</h3>
          <p>{stats.hd_non_rush}</p>
        </div>

      </div>

    </div>
  );
}

export default DashboardPage;