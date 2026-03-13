from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/track/{ref}")
def track(ref: str):
    return {"ref": ref}
