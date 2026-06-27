from fastapi import FastAPI

app = FastAPI(
    title="OLIM",
    description="Open Labeller for Interative Machine Learning",
    factory=True,
)
