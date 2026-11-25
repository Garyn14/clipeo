import { NavLink, Route, Routes } from "react-router-dom";
import "./App.css";
import { EstadoOperacion, useErroresPendientes } from "./components/ui";
import { Configuracion } from "./pages/Configuracion";
import { DetalleSesion } from "./pages/DetalleSesion";
import { Errores } from "./pages/Errores";
import { Fuentes } from "./pages/Fuentes";
import { Negocio } from "./pages/Negocio";
import { EstadoCorrida } from "./pages/EstadoCorrida";
import { NuevaCorrida } from "./pages/NuevaCorrida";
import { Publicaciones } from "./pages/Publicaciones";
import { RevisionClips } from "./pages/RevisionClips";
import { Sesiones } from "./pages/Sesiones";

const enlace = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-enlace active" : "nav-enlace");

function App() {
  const errores = useErroresPendientes();
  return (
    <div className="app">
      <aside className="sidebar">
        <NavLink to="/" className="marca" end>
          <span className="marca-punto" aria-hidden="true" />
          <span className="marca-nombre">
            Idea Millonaria
            <span className="marca-sub">clipeo · panel</span>
          </span>
        </NavLink>

        <nav className="nav-grupos">
          <div className="nav-grupo">
            <span className="nav-grupo-titulo">Producción</span>
            <NavLink to="/" end className={enlace}>
              Nueva corrida
            </NavLink>
            <NavLink to="/fuentes" className={enlace}>
              Fuentes
            </NavLink>
            <NavLink to="/sesiones" className={enlace}>
              Sesiones
            </NavLink>
            <NavLink to="/errores" className={enlace}>
              Errores
              {errores > 0 && <span className="nav-contador">{errores}</span>}
            </NavLink>
          </div>
          <div className="nav-grupo">
            <span className="nav-grupo-titulo">Distribución</span>
            <NavLink to="/publicaciones" className={enlace}>
              Publicaciones
            </NavLink>
          </div>
          <div className="nav-grupo">
            <span className="nav-grupo-titulo">Resultados</span>
            <NavLink to="/negocio" className={enlace}>
              Negocio
            </NavLink>
          </div>
          <div className="nav-grupo">
            <span className="nav-grupo-titulo">Ajustes</span>
            <NavLink to="/configuracion" className={enlace}>
              Configuración
            </NavLink>
          </div>
        </nav>

        <EstadoOperacion />
      </aside>

      <main className="contenido">
        <Routes>
          <Route path="/" element={<NuevaCorrida />} />
          <Route path="/runs/:runId" element={<EstadoCorrida />} />
          <Route path="/fuentes" element={<Fuentes />} />
          <Route path="/negocio" element={<Negocio />} />
          <Route path="/negocio/:nicho" element={<Negocio />} />
          <Route path="/sesiones" element={<Sesiones />} />
          <Route path="/sesiones/:sessionId" element={<DetalleSesion />} />
          <Route path="/sesiones/:sessionId/revision" element={<RevisionClips />} />
          <Route path="/errores" element={<Errores />} />
          <Route path="/publicaciones" element={<Publicaciones />} />
          <Route path="/publicaciones/:nicho" element={<Publicaciones />} />
          <Route path="/publicaciones/:nicho/:plataforma" element={<Publicaciones />} />
          <Route path="/configuracion" element={<Configuracion />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
