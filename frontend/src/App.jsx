import { NavLink, Route, Routes } from "react-router-dom";
import LiveFeed from "./pages/LiveFeed.jsx";
import CandidateDetail from "./pages/CandidateDetail.jsx";
import Journal from "./pages/Journal.jsx";

function NavItem({ to, children }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `px-3 py-2 rounded-lg text-sm font-medium transition ${
          isActive
            ? "bg-indigo-600 text-white"
            : "text-slate-300 hover:bg-slate-800 hover:text-white"
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
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <span className="text-lg font-semibold tracking-tight">
            🎴 PokeScanner
          </span>
          <nav className="flex gap-1">
            <NavItem to="/">Live Feed</NavItem>
            <NavItem to="/journal">Journal</NavItem>
          </nav>
          <span className="ml-auto text-xs text-slate-500">
            V1 · Messinstrument
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<LiveFeed />} />
          <Route path="/candidates/:id" element={<CandidateDetail />} />
          <Route path="/journal" element={<Journal />} />
        </Routes>
      </main>
    </div>
  );
}
