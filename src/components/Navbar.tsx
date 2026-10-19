import { NavLink } from "react-router";

export default function Navbar() {
  return (
    <nav className="navbar">
      <span>🐕 Disc Dog Tracker</span>
      <div>
        <NavLink to="/" end>Video Management</NavLink>
        <NavLink to="/history">Historical Trend</NavLink>
      </div>
    </nav>
  );
}