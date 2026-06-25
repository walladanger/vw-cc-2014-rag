FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py retrieve.py retrieve_video.py specverify.py web_server.py ./
COPY templates ./templates
COPY static ./static

ENV HOST=0.0.0.0
ENV PORT=5000
ENV VW_RAG_OUT=/data/out
ENV EMBEDDER=ollama

EXPOSE 5000
CMD ["python", "web_server.py"]
