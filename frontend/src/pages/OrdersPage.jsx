import { useState } from "react"
import OrdersTable from "../components/OrdersTable"

function OrdersPage(){

  const [service,setService] = useState("")
  const [rush,setRush] = useState("")
  const [status,setStatus] = useState("")

  return(

  <div className="page">

    <div className="orders-header">

      <div>

        <h1 className="page-title">
          Laundry Orders
        </h1>

        <div className="orders-stats">

          <div className="stat-box">
            <div className="stat-label">Orders</div>
            <div className="stat-value">87</div>
          </div>

          <div className="stat-box">
            <div className="stat-label">WF</div>
            <div className="stat-value">82</div>
          </div>

          <div className="stat-box">
            <div className="stat-label">HD</div>
            <div className="stat-value">5</div>
          </div>

        </div>

      </div>

      <div className="orders-actions">

        <select
        value={service}
        onChange={(e)=>setService(e.target.value)}
        className="filter">
          <option value="">All Services</option>
          <option value="WF">Wash & Fold</option>
          <option value="HD">Hang Dry</option>
        </select>

        <select
        value={rush}
        onChange={(e)=>setRush(e.target.value)}
        className="filter">
          <option value="">All Rush</option>
          <option value="RUSH">Rush</option>
          <option value="NON-RUSH">Normal</option>
        </select>

        <select
        value={status}
        onChange={(e)=>setStatus(e.target.value)}
        className="filter">
          <option value="">All Status</option>
          <option value="PENDING">Pending</option>
          <option value="COMPLETE">Complete</option>
        </select>

        <button className="action-btn">
          Refresh
        </button>

      </div>

    </div>

    <OrdersTable
      service={service}
      rush={rush}
      status={status}
    />

  </div>

  )

}

export default OrdersPage