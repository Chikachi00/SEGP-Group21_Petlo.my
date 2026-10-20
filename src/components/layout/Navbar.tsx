import { NavLink } from "react-router";

export default function Navbar() {
  return (
    <nav className="navbar" aria-label="Main navigation">
      <NavLink className="brand" to="/">Disc Dog Tracker</NavLink>
      <div>
        <NavLink to="/" end>Video Management</NavLink>
        <NavLink to="/history">Historical Trend</NavLink>
      </div>
    </nav>
  );
}
