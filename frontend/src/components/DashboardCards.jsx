function DashboardCards({stats}){

return(

<div className="cards-grid">

<Card title="Total Orders" value={stats.total_orders}/>
<Card title="WF Orders" value={stats.wf_total}/>
<Card title="HD Orders" value={stats.hd_total}/>
<Card title="WF Rush" value={stats.wf_rush}/>
<Card title="HD Rush" value={stats.hd_rush}/>

</div>

)

}

function Card({title,value}){

return(

<motion.div
className="card"
whileHover={{scale:1.05}}
>

<div className="card-title">{title}</div>

<div className="card-value">{value}</div>

</motion.div>

)

}

export default DashboardCards