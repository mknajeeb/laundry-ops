import { useState } from "react";

function ProductionPage() {

  const [employee,setEmployee] = useState("");
  const [orders,setOrders] = useState("");

  const startShift = () => {
    console.log("Started:",employee,orders);
  };

  return (

    <div style={{padding:30}}>

      <h1>Production</h1>

      <div style={{marginTop:20}}>

        <input
          placeholder="Employee"
          value={employee}
          onChange={(e)=>setEmployee(e.target.value)}
        />

      </div>

      <div style={{marginTop:10}}>

        <input
          placeholder="Orders processed"
          value={orders}
          onChange={(e)=>setOrders(e.target.value)}
        />

      </div>

      <button
        onClick={startShift}
        style={{marginTop:15}}
      >
        Start Production
      </button>

    </div>

  );

}

export default ProductionPage;