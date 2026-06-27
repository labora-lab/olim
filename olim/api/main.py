from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from olim.api.exceptions import APIError
from olim.api.routers import annotations, datasets, items, pipelines, runs, schemes

app = FastAPI(title="OLIM", description="Open Labeller for Interative Machine Learning")


@app.exception_handler(APIError)
def handle_api_error(_: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(datasets.router)
app.include_router(items.router)
app.include_router(schemes.router)
app.include_router(annotations.router)
app.include_router(pipelines.router)
app.include_router(runs.router)
