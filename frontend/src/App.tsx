import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { CisoView } from "./pages/CisoView";
import { TechnicalView } from "./pages/TechnicalView";

export default function App() {
  return (
    <>
      <header>
        <h1>Azure Compliancy Dashboard</h1>
        <nav aria-label="Primary">
          <NavLink to="/technical">Technical</NavLink> <NavLink to="/ciso">CISO</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/technical" replace />} />
          <Route path="/technical" element={<TechnicalView />} />
          <Route path="/ciso" element={<CisoView />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </>
  );
}
