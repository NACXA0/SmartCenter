import { NavLink } from "react-router-dom";
import * as Tooltip from "@radix-ui/react-tooltip";
import { ScanFace } from "lucide-react";
import { NAV } from "./nav";

export function Sidebar() {
  return (
    <aside className="sidebar" aria-label="主导航">
      <div className="brand" title="SmartCenter">
        <ScanFace size={20} strokeWidth={2.2} />
      </div>
      <Tooltip.Provider delayDuration={200}>
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <Tooltip.Root key={item.id}>
              <Tooltip.Trigger asChild>
                <NavLink
                  to={item.path}
                  className={({ isActive }) => `nav-btn${isActive ? " active" : ""}`}
                  aria-label={item.label}
                >
                  <Icon size={20} strokeWidth={2} />
                </NavLink>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content className="tooltip" side="right" sideOffset={8}>
                  {item.label}
                  <Tooltip.Arrow style={{ fill: "#0a0e13" }} />
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          );
        })}
      </Tooltip.Provider>
      <div className="spacer" />
    </aside>
  );
}
