import os
import psycopg2
from fastapi import FastAPI, HTTPException

app = FastAPI()

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "appuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "apppass")
DB_NAME = os.getenv("DB_NAME", "appdb")


def get_db_stats():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
        return {"version": version}
    finally:
        conn.close()


@app.get("/")
async def root():
    try:
        stats = get_db_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")
    return {
        "status": "ok",
        "runtime": "python",
        "db": stats,
    }
