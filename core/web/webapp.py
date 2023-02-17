
from fastapi import FastAPI
from fastapi import APIRouter
from mongoengine import connect

from core.web.apiv2 import observables
from core.config.config import yeti_config


connect(
    yeti_config.mongodb.database,
    host=yeti_config.mongodb.host,
    port=yeti_config.mongodb.port,
    username=yeti_config.mongodb.username,
    password=yeti_config.mongodb.password,
    connect=False,
    tls=False,
)




app = FastAPI()
api_router = APIRouter()


@api_router.get("/")
async def api_root():
    return {"message": "(API) Hello World"}

@app.get("/")
async def root():
    return {"message": "Hello World"}

api_router.include_router(observables.observables_router, prefix="/observables", tags=["observables"])

app.include_router(api_router, prefix="/api/v2")
