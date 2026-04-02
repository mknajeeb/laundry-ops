import rinse from "../assets/Rinse.png"
import washpro from "../assets/Washpro.png"

function Header(){

return (

<div className="header">

<img src={washpro} className="logo-left" alt="Laundry Ops" />

<h1>Laundry Operations System</h1>

<img src={rinse} className="logo-right"/>

</div>

)

}

export default Header