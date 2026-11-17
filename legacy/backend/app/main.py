from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.publicacion import motor
from app.routers import clips, config, errores, publicaciones, runs, sessions
from app.services import review_actions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Texto para TikTok de las publicaciones encoladas antes de que existiera (idempotente)
    review_actions.completar_textos_publicacion()
    # Motor de publicación: revisa al arrancar y cada 10 min (PUBLICACION_MOTOR=0 lo apaga)
    motor.iniciar()
    yield
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


@app.get("/health")
def health():
    return {"ok": True}
