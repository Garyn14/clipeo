import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import "./App.css";
import { Configuracion } from "./pages/Configuracion";
import { DetalleSesion } from "./pages/DetalleSesion";
import { Errores } from "./pages/Errores";
import { EstadoCorrida } from "./pages/EstadoCorrida";
import { NuevaCorrida } from "./pages/NuevaCorrida";
import { Publicaciones } from "./pages/Publicaciones";
import { RevisionClips } from "./pages/RevisionClips";
import { Sesiones } from "./pages/Sesiones";

function App() {
  return (
    <div className="app">
      <nav className="nav">
        <span className="brand">Idea Millonaria</span>
        <NavLink to="/" end>
          Nueva corrida
        </NavLink>
        <NavLink to="/sesiones">Sesiones</NavLink>
        <NavLink to="/errores">Errores</NavLink>
        <NavLink to="/publicaciones">Publicaciones</NavLink>
        <NavLink to="/configuracion">Configuración</NavLink>
      </nav>

      <main>
        <Routes>
          <Route path="/" element={<NuevaCorrida />} />
          <Route path="/runs/:runId" element={<EstadoCorrida />} />
          <Route path="/sesiones" element={<Sesiones />} />
          <Route path="/sesiones/:sessionId" element={<DetalleSesion />} />
          <Route path="/sesiones/:sessionId/revision" element={<RevisionClips />} />
          <Route path="/errores" element={<Errores />} />
          <Route path="/publicaciones" element={<Navigate to="/publicaciones/tiktok" replace />} />
          <Route path="/publicaciones/:plataforma" element={<Publicaciones />} />
          <Route path="/configuracion" element={<Configuracion />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
