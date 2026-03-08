import { useEffect, useState } from "react";
import axios from "axios";
import DashboardCards from "../components/DashboardCards";

function Dashboard() {

  const [stats, setStats] = useState(null);

  useEffect(() => {

    axios
      .get("http://localhost:8000/dashboard")
      .then(res => {
        setStats(res.data);
      })
      .catch(err => {
        console.error("Dashboard error:", err);
      });

  }, []);

  if (!stats) {
    return <div style={{padding:40}}>Loading dashboard...</div>;
  }

  return (

    <div className="dashboard-container">

      <h1>Operations Dashboard</h1>

      <DashboardCards stats={stats} />

    </div>

  );

}

export default Dashboard;