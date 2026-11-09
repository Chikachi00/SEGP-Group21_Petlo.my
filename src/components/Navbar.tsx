import { NavLink } from "react-router";
import PawLogo from "./PawLogo";

export default function Navbar() {
  return (
    <nav className="navbar" aria-label="Main navigation">
      <NavLink className="brand" to="/">
        <PawLogo />
        <span>Disc Dog Tracker</span>
      </NavLink>

      <div className="nav-links">
        <NavLink to="/">Video Management</NavLink>
        <NavLink to="/history">Historical Trend</NavLink>
      </div>
    </nav>
  );
}
