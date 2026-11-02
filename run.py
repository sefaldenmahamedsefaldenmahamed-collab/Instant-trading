"""Local entrypoint: python run.py  →  http://localhost:8000"""
import uvicorn

from app.config import CFG

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=CFG.host, port=CFG.port, log_level=CFG.log_level.lower())
