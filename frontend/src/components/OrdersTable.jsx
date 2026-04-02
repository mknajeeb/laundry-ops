import { useEffect, useState } from "react"
import { getOrders } from "../api"
import { motion } from "framer-motion"

const MotionDiv = motion.div

function OrdersTable({ service, rush, status }) {

  const [orders,setOrders] = useState([])
  const [search,setSearch] = useState("")

  useEffect(()=>{

    getOrders()
      .then(res=>{

        if(Array.isArray(res.data)){
          setOrders(res.data)
        }else if(Array.isArray(res.data.orders)){
          setOrders(res.data.orders)
        }else{
          console.log("Unexpected response",res.data)
          setOrders([])
        }

      })
      .catch(err=>{
        console.error(err)
        setOrders([])
      })

  },[])

  const filtered = Array.isArray(orders)
    ? orders.filter(o => {

        const nameMatch =
          (o.name_clean || "")
          .toLowerCase()
          .includes(search.toLowerCase())

        const serviceMatch =
          !service || o.service_type === service

        const rushMatch =
          !rush || o.rush_type === rush

        const statusMatch =
          !status || o.status === status

        return nameMatch && serviceMatch && rushMatch && statusMatch

      })
    : []

  return (

    <div>

      <input
        className="search-box"
        placeholder="Search name..."
        value={search}
        onChange={(e)=>setSearch(e.target.value)}
      />

      <div className="orders-grid">

        {filtered.map(order=>(

          <MotionDiv
            key={order.id}
            className={`order-card ${order.rush_type === "RUSH" ? "rush":""}`}
            whileHover={{scale:1.03}}
          >

            <div className="order-name">
              {order.name_clean || "-"}
            </div>

            <div className="order-meta">
              <span>{order.service_type || "-"}</span>
              <span>
                {order.date_clean
                  ? new Date(order.date_clean).toLocaleDateString()
                  : "-"}
              </span>
            </div>

            <div className="order-status">
              {order.status || "PENDING"}
            </div>

          </MotionDiv>

        ))}

      </div>

    </div>

  )

}

export default OrdersTable
