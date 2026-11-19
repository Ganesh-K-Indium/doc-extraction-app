# One Dockerfile for the whole product, with two targets that docker-compose.yml builds:
#   backend   the API: Tesseract, every local OCR engine and their models, so it needs no setup and no internet at runtime
#   frontend  the web app, built once and served by nginx, which also forwards /api to the backend
# Build context is the repository root.

# ---------------------------------------------------------------- backend
FROM python:3.12-slim AS backend

# Tesseract for scans; libgl1 / libglib2.0-0 are what OpenCV (used by PaddleOCR and docTR) needs on a slim image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ocr.txt

COPY backend/app ./app

# Uploads, the database and saved settings live in /data (mount a volume). The OCR models are baked into the image at /opt/models.
ENV DATA_DIR=/data MODELS_DIR=/opt/models PYTHONUNBUFFERED=1
# Fails the build if an engine cannot load or read the sample page, instead of failing on the first upload.
RUN python -m app.engines.warmup paddleocr doctr rapidocr tesseract

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- web app, built
FROM node:22-alpine AS web-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
# Empty means "same origin": requests go to /api on the address the page came from (see nginx.conf.template).
ENV VITE_API_BASE_URL=""
RUN npm run build

# ---------------------------------------------------------------- frontend
FROM nginx:1.27-alpine AS frontend
# The official image fills ${BACKEND_URL} and ${APP_API_KEY} into this template when the container starts.
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=web-build /app/dist /usr/share/nginx/html
ENV BACKEND_URL=http://backend:8000 APP_API_KEY=
EXPOSE 80
