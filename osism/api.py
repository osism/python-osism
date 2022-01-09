from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware
)

@app.get("/")
async def root():
    return {"message": "Hello World"}
