import { useEffect, useState } from "react"
import { getOrders } from "../api"

function OrdersPage(){

  const [orders,setOrders] = useState([])
  const [search,setSearch] = useState("")

  useEffect(()=>{
    loadOrders()
  },[])

  const loadOrders = ()=>{
    getOrders().then(res=>{
      setOrders(res.data)
    })
  }

  const filtered = orders.filter(o=>{
    if(!search) return true
    return o.name_clean?.toLowerCase().includes(search.toLowerCase())
  })

  const totalOrders = filtered.length

  const totalWeight = filtered.reduce((sum,o)=>{
    if(!o.weight_num) return sum
    return sum + Number(o.weight_num)
  },0)

  return(

    <div className="page">

      <div className="orders-top">

        <h1 className="page-title">Laundry Orders</h1>

        <div className="orders-stats">

          <div className="stat-box">
            <div className="stat-label">Orders</div>
            <div className="stat-value">{totalOrders}</div>
          </div>

          <div className="stat-box">
            <div className="stat-label">Weight</div>
            <div className="stat-value">{totalWeight.toFixed(2)} lbs</div>
          </div>

        </div>

      </div>

      <input
        className="search-box"
        placeholder="Search name..."
        value={search}
        onChange={(e)=>setSearch(e.target.value)}
      />

      <div className="table-wrapper">

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

            {filtered.map(o=>(
              <tr key={o.id}>

                <td>{o.id}</td>

                <td>
                  {new Date(o.date_clean).toLocaleDateString()}
                </td>

                <td className="name-cell">
                  {o.name_clean}
                </td>

                <td>{o.weight_num || "-"}</td>

                <td>{o.service_type}</td>

                <td>
                  <span className="status-pill">
                    {o.status}
                  </span>
                </td>

              </tr>
            ))}

          </tbody>

        </table>

      </div>

    </div>

  )
}

export default OrdersPage