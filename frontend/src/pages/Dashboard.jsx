import { useEffect, useState } from "react"
import { getDashboard } from "../api"
import DashboardCards from "../components/DashboardCards"

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

    <DashboardCards stats={stats}/>

  </div>

  )

}

export default Dashboard