import { useEffect, useState } from "react"
import axios from "axios"
import { motion } from "framer-motion"

function OrdersGrid(){

  const [orders,setOrders] = useState([])
  const [search,setSearch] = useState("")

  useEffect(()=>{
    axios.get("/orders")
      .then(res => setOrders(res.data))
      .catch(err => console.error(err))
  },[])

  const filtered = orders.filter(o =>
    (o.name_clean || "").toLowerCase().includes(search.toLowerCase())
  )

  return(

  <div className="page">

    <h1 className="page-title">Laundry Orders</h1>

    <input
      className="search-box"
      placeholder="Search name..."
      value={search}
      onChange={(e)=>setSearch(e.target.value)}
    />

    <div className="orders-grid">

      {filtered.map(order => (

        <motion.div
          key={order.id}
          className={`order-card ${order.rush_type === "RUSH" ? "rush" : ""}`}
          whileHover={{scale:1.03}}
        >

          <div className="order-name">
            {order.name_clean}
          </div>

          <div className="order-meta">

            <span>{order.service_type}</span>

            <span>
              {new Date(order.date_clean).toLocaleDateString()}
            </span>

          </div>

          <div className="order-status">
            {order.status}
          </div>

        </motion.div>

      ))}

    </div>

  </div>

  )

}

export default OrdersGrid