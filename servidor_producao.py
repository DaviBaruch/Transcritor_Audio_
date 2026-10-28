"""Entrada do servidor de produção. HTTPS deve ficar em um proxy reverso."""

import os

from waitress import serve

from app import app


host = os.getenv("TRANSCRITOR_HOST", "0.0.0.0")
porta = int(os.getenv("TRANSCRITOR_PORT") or os.getenv("PORT", "5055"))
serve(app, host=host, port=porta, threads=int(os.getenv("TRANSCRITOR_THREADS", "4")))
