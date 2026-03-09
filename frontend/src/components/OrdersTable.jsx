import { useEffect, useState } from "react"
import axios from "axios"

function OrdersTable(){

  const [orders,setOrders] = useState([])
  const [search,setSearch] = useState("")

  useEffect(()=>{
    loadOrders()
  },[])

  const loadOrders = ()=>{
    axios.get("/orders")
      .then(res=>{
        setOrders(res.data)
      })
      .catch(err=>{
        console.error("Error loading orders:", err)
      })
  }

  const filtered = orders.filter(order =>
    (order.name || "")
      .toLowerCase()
      .includes(search.toLowerCase())
  )

  const totalWeight = orders.reduce(
    (sum,order)=>sum + (order.weight || 0),
    0
  )

  return(

  <>

    {/* TOP BAR */}

    <div className="orders-top">

      <div className="orders-filters">

        <input
          className="search-box"
          placeholder="Search name..."
          value={search}
          onChange={(e)=>setSearch(e.target.value)}
        />

      </div>

      <div className="orders-stats">

        <div className="stat-box">
          <div className="stat-label">Orders</div>
          <div className="stat-value">{orders.length}</div>
        </div>

        <div className="stat-box">
          <div className="stat-label">Weight</div>
          <div className="stat-value">{totalWeight} lbs</div>
        </div>

      </div>

    </div>

    {/* TABLE */}

    <table className="orders-table">

      <thead>
        <tr>
          <th>#</th>
          <th>Date</th>
          <th>Name</th>
          <th>Weight</th>
          <th>Service</th>
          <th>Status</th>
        </tr>
      </thead>

      <tbody>

      {filtered.map(order => (

        <tr key={order.id}>

          <td>{order.id}</td>

          <td>
            {order.date
              ? new Date(order.date).toLocaleDateString()
              : "-"
            }
          </td>

          <td>{order.name}</td>

          <td>{order.weight || "-"}</td>

          <td>{order.service}</td>

          <td>
            <span className="status pending">
              {order.status || "PENDING"}
            </span>
          </td>

        </tr>

      ))}

      </tbody>

    </table>

  </>

  )

}

export default OrdersTable