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
          <h3>Total Orders</h3>
          <p>{stats.total_orders || 0}</p>
        </motion.div>

        <motion.div className="card" whileHover={{scale:1.04}}>
          <h3>WF Orders</h3>
          <p>{stats.wf_total || 0}</p>
        </motion.div>

        <motion.div className="card" whileHover={{scale:1.04}}>
          <h3>HD Orders</h3>
          <p>{stats.hd_total || 0}</p>
        </motion.div>

        <motion.div className="card" whileHover={{scale:1.04}}>
          <h3>WF Rush</h3>
          <p>{stats.wf_rush || 0}</p>
        </motion.div>

        <motion.div className="card" whileHover={{scale:1.04}}>
          <h3>HD Rush</h3>
          <p>{stats.hd_rush || 0}</p>
        </motion.div>

      </div>

    </div>

  )
}

export default Dashboard