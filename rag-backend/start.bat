@echo off
cd /d "E:\??\rag-backend"
set PYTHONPATH=E:\??\rag-backend
"E:\RAG\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000 > "E:\??\rag-backend\logs\server.log" 2>&1
