import { NavLink } from "react-router-dom";
import { NAV } from "./nav";

export function BottomNav() {
  return (
    <nav className="bottomnav" aria-label="移动导航">
      {NAV.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.id}
            to={item.path}
            className={({ isActive }) => `nav-btn${isActive ? " active" : ""}`}
          >
            <Icon size={18} strokeWidth={2} />
            <span>{item.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
