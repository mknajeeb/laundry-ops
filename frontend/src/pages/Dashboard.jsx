import { useEffect, useState } from "react"
import { motion } from "framer-motion"
import { getDashboard } from "../api"

const MotionDiv = motion.div

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

      <MotionDiv className="card" whileHover={{scale:1.04}}>
        <div className="card-label">Total Orders</div>
        <div className="card-value">{stats.total_orders}</div>
      </MotionDiv>

      <MotionDiv className="card" whileHover={{scale:1.04}}>
        <div className="card-label">WF Orders</div>
        <div className="card-value">{stats.wf_total}</div>
      </MotionDiv>

      <MotionDiv className="card" whileHover={{scale:1.04}}>
        <div className="card-label">HD Orders</div>
        <div className="card-value">{stats.hd_total}</div>
      </MotionDiv>

      <MotionDiv className="card" whileHover={{scale:1.04}}>
        <div className="card-label">WF Rush</div>
        <div className="card-value">{stats.wf_rush}</div>
      </MotionDiv>

      <MotionDiv className="card" whileHover={{scale:1.04}}>
        <div className="card-label">HD Rush</div>
        <div className="card-value">{stats.hd_rush}</div>
      </MotionDiv>

    </div>

  </div>

  )

}

export default Dashboard
