import { NavLink, Outlet } from "react-router-dom";

import HealthBadge from "./HealthBadge";

const NAV = [
  { to: "/", label: "Scope", glyph: "⊹", end: true },
  { to: "/dashcam", label: "Dashcam", glyph: "▶", end: false },
  { to: "/history", label: "Log", glyph: "≡", end: false },
  { to: "/system", label: "System", glyph: "◊", end: false },
];

function navClass({ isActive }: { isActive: boolean }) {
  return [
    "flex items-center gap-3 rounded-md px-3 py-2 font-mono text-xs uppercase tracking-wider transition-colors",
    isActive ? "bg-lime/10 text-lime" : "text-ash hover:text-bone",
  ].join(" ");
}

export default function AppShell() {
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      {/* Desktop rail */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-edge px-4 py-6 md:flex">
        <Brand />
        <nav className="mt-10 flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={navClass}>
              <span className="text-base leading-none text-lime/80">{n.glyph}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <HealthBadge />
          <LicenseNote />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile header */}
        <header className="flex items-center justify-between border-b border-edge px-4 py-3 md:hidden">
          <Brand compact />
          <HealthBadge />
        </header>

        <main className="flex-1 px-4 py-6 pb-24 md:px-8 md:py-8 md:pb-8">
          <Outlet />
        </main>

        {/* Mobile bottom tabs */}
        <nav className="fixed inset-x-0 bottom-0 z-50 flex border-t border-edge bg-coal/95 backdrop-blur md:hidden">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                [
                  "flex flex-1 flex-col items-center gap-1 py-3 font-mono text-[10px] uppercase tracking-wider",
                  isActive ? "text-lime" : "text-ash",
                ].join(" ")
              }
            >
              <span className="text-lg leading-none">{n.glyph}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="leading-none">
      <div className="font-display text-lg font-extrabold tracking-tight text-bone">
        LOCATE<span className="text-lime">/</span>ANYTHING
      </div>
      {!compact && (
        <div className="label-kicker mt-1">vision grounding console</div>
      )}
    </div>
  );
}

function LicenseNote() {
  return (
    <p className="mt-4 font-mono text-[9px] leading-relaxed text-ash/70">
      Model: NVIDIA LocateAnything-3B —{" "}
      <a
        href="https://huggingface.co/nvidia/LocateAnything-3B"
        target="_blank"
        rel="noreferrer"
        className="underline hover:text-ash"
      >
        non-commercial license
      </a>
      . UI is Apache-2.0.
    </p>
  );
}
