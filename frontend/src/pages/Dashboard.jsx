import { useEffect, useState } from "react"
import { motion } from "framer-motion"
import { getDashboard } from "../api"

function Dashboard(){

  const [stats,setStats] = useState({})

  useEffect(()=>{
    getDashboard().then(res=>{
      setStats(res.data)
    })
  },[])

  return(

  <div className="page">

    <h1 className="page-title">Operations Dashboard</h1>

    <div className="cards">

      <motion.div className="card" whileHover={{scale:1.04}}>
        <div className="card-label">Total Orders</div>
        <div className="card-value">{stats.total_orders}</div>
      </motion.div>

      <motion.div className="card" whileHover={{scale:1.04}}>
        <div className="card-label">WF Orders</div>
        <div className="card-value">{stats.wf_total}</div>
      </motion.div>

      <motion.div className="card" whileHover={{scale:1.04}}>
        <div className="card-label">HD Orders</div>
        <div className="card-value">{stats.hd_total}</div>
      </motion.div>

      <motion.div className="card" whileHover={{scale:1.04}}>
        <div className="card-label">WF Rush</div>
        <div className="card-value">{stats.wf_rush}</div>
      </motion.div>

      <motion.div className="card" whileHover={{scale:1.04}}>
        <div className="card-label">HD Rush</div>
        <div className="card-value">{stats.hd_rush}</div>
      </motion.div>

    </div>

  </div>

  )

}

export default Dashboard