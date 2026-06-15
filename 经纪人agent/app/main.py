from fastapi import FastAPI

from app.api.routes import router


app = FastAPI(title="Insurance Product Research Agent")
app.include_router(router)
