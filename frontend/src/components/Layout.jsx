import { Link } from "react-router-dom"
import { LayoutDashboard, Package, Upload, Users } from "lucide-react"

function Layout({ children }) {

return (

<div className="app-layout">

<aside className="sidebar">

<h2>LaundryOps</h2>

<div className="sidebar-menu">

<Link className="menu-item" to="/">
<LayoutDashboard size={18}/> Dashboard
</Link>

<Link className="menu-item" to="/checkout">
<Package size={18}/> Rush Bag Checkout
</Link>

<Link className="menu-item" to="/upload">
<Upload size={18}/> Upload
</Link>

<Link className="menu-item" to="/employees">
<Users size={18}/> Employees
</Link>

</div>

</aside>

<main className="main-content">

{children}

</main>

</div>

)

}

export default Layout