import { Link } from "react-router-dom";

function Sidebar(){

  return(

    <div className="sidebar">

      <h2>Washpro</h2>

      <div className="sidebar-menu">
        <Link className="menu-item" to="/">Home</Link>

        <Link className="menu-item" to="/dashboard">Dashboard</Link>

        <Link className="menu-item" to="/orders">Orders</Link>

        <Link className="menu-item" to="/checkout">Checkout</Link>

        <Link className="menu-item" to="/employees">Employees</Link>
        <Link className="menu-item" to="/clock">Clock</Link>

        <Link className="menu-item" to="/issues">Issues</Link>

        <Link className="menu-item" to="/production">Production</Link>

        <Link className="menu-item" to="/scoreboard">Scoreboard</Link>

        <Link className="menu-item" to="/maintenance">Maintenance</Link>

      </div>

    </div>

  );

}

export default Sidebar;
