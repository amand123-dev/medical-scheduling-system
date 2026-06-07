from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.identity.router import router as identity_router
from app.scheduling.router import router as scheduling_router

app = FastAPI(
    title="SmallPractice Scheduler",
    description="HIPAA-aware appointment scheduling for solo and small medical practices.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(identity_router)
app.include_router(scheduling_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
