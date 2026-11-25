from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.directos import vigilante
from app.publicacion import motor
from app.routers import clips, config, directos, errores, estado, publicaciones, runs, sessions, fuentes, negocio
from app.services import review_actions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Texto para TikTok de las publicaciones encoladas antes de que existiera (idempotente)
    review_actions.completar_textos_publicacion()
    # Motor de publicación: revisa al arrancar y cada 10 min (PUBLICACION_MOTOR=0 lo apaga)
    motor.iniciar()
    # CLIP-88: vigilante de directos (DIRECTOS_MOTOR=0 lo apaga)
    vigilante.iniciar()
    yield
    vigilante.detener()
    motor.detener()


app = FastAPI(title="Idea Millonaria — Panel", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router)
app.include_router(sessions.router)
app.include_router(runs.router)
app.include_router(clips.router)
app.include_router(errores.router)
app.include_router(publicaciones.router)
app.include_router(fuentes.router)   # S14: fuentes estáticas por nicho
app.include_router(negocio.router)   # S17: reporte de negocio por cliente
app.include_router(estado.router)    # CLIP-84: estado de la operación (pie de la barra lateral)
app.include_router(directos.router)  # CLIP-88: directos en vivo (épica L1)


@app.get("/health")
def health():
    return {"ok": True}
