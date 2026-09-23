import { NavLink, Route, Routes } from "react-router-dom";
import LiveFeed from "./pages/LiveFeed.jsx";
import Auctions from "./pages/Auctions.jsx";
import CandidateDetail from "./pages/CandidateDetail.jsx";
import Journal from "./pages/Journal.jsx";
import Inventory from "./pages/Inventory.jsx";
import Calibration from "./pages/Calibration.jsx";
import Costs from "./pages/Costs.jsx";
import Diagnostics from "./pages/Diagnostics.jsx";

// Navigation ohne Pillen: eine Unterstreichung reicht. Ein farbiger Block je
// Menuepunkt zieht mehr Aufmerksamkeit auf die Navigation als auf die Daten —
// und die Daten sind der Grund, warum jemand herkommt.
function NavItem({ to, children }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `relative px-1 py-3 text-sm transition-colors ${
          isActive
            ? "text-paper after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-water"
            : "text-paper-muted hover:text-paper"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] items-center gap-8 px-5">
          <span className="font-mono text-sm font-bold tracking-widest text-paper">
            POKESCANNER
          </span>
          <nav className="flex gap-6">
            <NavItem to="/">Feed</NavItem>
            <NavItem to="/auctions">Auktionen</NavItem>
            <NavItem to="/inventory">Inventar</NavItem>
            <NavItem to="/journal">Journal</NavItem>
            <NavItem to="/calibration">Kalibrierung</NavItem>
            <NavItem to="/diagnostics">Diagnose</NavItem>
            <NavItem to="/costs">Kosten</NavItem>
          </nav>
          <span className="ml-auto font-mono text-2xs uppercase tracking-widest text-paper-dim">
            V1 · Messinstrument
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-6">
        <Routes>
          <Route path="/" element={<LiveFeed />} />
          <Route path="/auctions" element={<Auctions />} />
          <Route path="/candidates/:id" element={<CandidateDetail />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/calibration" element={<Calibration />} />
          <Route path="/diagnostics" element={<Diagnostics />} />
          <Route path="/costs" element={<Costs />} />
        </Routes>
      </main>
    </div>
  );
}
