import { useState } from "react";

function Checkoutpage() {

  const [driver,setDriver] = useState("");
  const [bag,setBag] = useState("");
  const [checked,setChecked] = useState([]);

  const checkoutBag = () => {

    if(!bag) return;

    setChecked([
      ...checked,
      {
        bag: bag,
        driver: driver,
        time: new Date().toLocaleTimeString()
      }
    ]);

    setBag("");
  };

  return (

    <div style={{padding:"30px"}}>

      <h1>Driver Checkout</h1>

      <div style={{marginTop:"20px"}}>

        <label>Driver</label>

        <input
          value={driver}
          onChange={(e)=>setDriver(e.target.value)}
          placeholder="Driver name"
          style={{marginLeft:10,padding:6}}
        />

      </div>

      <div style={{marginTop:"15px"}}>

        <label>Bag</label>

        <input
          value={bag}
          onChange={(e)=>setBag(e.target.value)}
          placeholder="Scan bag"
          style={{marginLeft:10,padding:6}}
        />

        <button
          onClick={checkoutBag}
          style={{
            marginLeft:10,
            padding:"6px 12px",
            background:"#2563eb",
            color:"white",
            border:"none"
          }}
        >
          Checkout
        </button>

      </div>

      <table style={{marginTop:30,width:"100%"}}>

        <thead>
          <tr>
            <th>Bag</th>
            <th>Driver</th>
            <th>Time</th>
          </tr>
        </thead>

        <tbody>

          {checked.map((c,i)=>(
            <tr key={i}>
              <td>{c.bag}</td>
              <td>{c.driver}</td>
              <td>{c.time}</td>
            </tr>
          ))}

        </tbody>

      </table>

    </div>

  );

}

export default Checkoutpage;