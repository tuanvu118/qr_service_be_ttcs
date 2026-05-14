from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from configs.settings import get_cors_origins


def register_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
