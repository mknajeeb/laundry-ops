import { useEffect, useState } from "react"
import axios from "axios"

function OrdersTable(){

  const [orders,setOrders] = useState([])
  const [search,setSearch] = useState("")

  useEffect(()=>{
    loadOrders()
  },[])

  const loadOrders = ()=>{
    axios.get("https://laundryops-api-dscucxa8c6dbghd9.centralus-01.azurewebsites.net/orders")
      .then(res=>{
        setOrders(res.data)
      })
      .catch(err=>{
        console.error("Error loading orders:", err)
      })
  }

  const filtered = orders.filter(order =>
    (order.name_clean || "")
      .toLowerCase()
      .includes(search.toLowerCase())
  )

  const totalWeight = orders.reduce(
    (sum,order)=>sum + (order.weight_num || 0),
    0
  )

  return(

  <>

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

    <table className="orders-table">

      <thead>
        <tr>
          <th>#</th>
          <th>Date</th>
          <th>Name</th>
          <th>Weight</th>
          <th>Service</th>
          <th>Rush</th>
          <th>Status</th>
        </tr>
      </thead>

      <tbody>

      {filtered.map(order => (

        <tr key={order.id}>

          <td>{order.id}</td>

          <td>
            {order.date_clean
              ? new Date(order.date_clean).toLocaleDateString()
              : "-"
            }
          </td>

          <td>{order.name_clean}</td>

          <td>{order.weight_num || "-"}</td>

          <td>{order.service_type}</td>

          <td>{order.rush_type}</td>

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