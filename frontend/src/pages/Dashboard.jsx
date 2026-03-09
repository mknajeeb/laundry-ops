import { useEffect, useState } from "react";
import axios from "axios";
import "./dashboard.css";

function Dashboard() {

  const [orders,setOrders] = useState([]);

  useEffect(()=>{
    axios.get("http://localhost:5001/orders")
      .then(res => setOrders(res.data))
  },[])

  const totalOrders = orders.length;

  const totalWeight = orders.reduce((sum,o)=>{
    return sum + Number(o.weight || 0);
  },0);

  const rushOrders = orders.filter(o => o.rush === 1).length;

  const hdOrders = orders.filter(o => o.service_type === "HD").length;

  const wfOrders = orders.filter(o => o.service_type === "WF").length;

  return (

    <div className="dashboard">

      <h1 className="page-title">Operations Dashboard</h1>

      <div className="cards-grid">

        <div className="card">
          <div className="card-title">Total Orders</div>
          <div className="card-value">{totalOrders}</div>
        </div>

        <div className="card">
          <div className="card-title">Total Weight</div>
          <div className="card-value">{totalWeight} lb</div>
        </div>

        <div className="card">
          <div className="card-title">Rush Orders</div>
          <div className="card-value">{rushOrders}</div>
        </div>

        <div className="card">
          <div className="card-title">Wash & Fold</div>
          <div className="card-value">{wfOrders}</div>
        </div>

        <div className="card">
          <div className="card-title">Hang Dry</div>
          <div className="card-value">{hdOrders}</div>
        </div>

      </div>

    </div>

  )
}

export default Dashboard;