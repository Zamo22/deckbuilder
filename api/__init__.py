"""HTTP API wrapping the engine.

Local dev:   `uvicorn api.main:app --reload --port 8000`
Production:  Vercel serverless via @vercel/python ASGI support
             (vercel.json rewrites /api/* to api/main.py).
"""
