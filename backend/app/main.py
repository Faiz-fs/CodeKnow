"""CodeKnow FastAPI application entrypoint."""

from fastapi import FastAPI, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import CodeKnowException
from app.routers import analyze, auth, github, health

settings = get_settings()

app = FastAPI(
    title="CodeKnow",
    description="Codebase intelligence & knowledge-retention platform.",
    version="0.1.0",
)

# Register global exception handler for CodeKnowException
@app.exception_handler(CodeKnowException)
async def codeknow_exception_handler(request: Request, exc: CodeKnowException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.detail,
                "status": exc.status_code,
            }
        },
        headers=exc.headers,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/codeknow"

api_route = APIRouter(prefix=API_PREFIX)
api_route.include_router(health.router)
api_route.include_router(auth.router, prefix="/auth")
api_route.include_router(analyze.router, prefix="/analyze")
api_route.include_router(github.router, prefix="/github")

app.include_router(api_route)


@app.get("/")
def root():
    return {"service": "CodeKnow", "version": "0.1.0", "docs": "/docs"}
