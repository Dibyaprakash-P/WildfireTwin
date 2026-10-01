# WildfireTwin backend (FastAPI). CPU PyTorch for portability; ML training stays a local/offline process.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r /app/requirements.txt

# Shared libraries required by the rasterio/GDAL wheel (libexpat) and PyTorch CPU threading (libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libgomp1  && rm -rf /var/lib/apt/lists/*

COPY config /app/config
COPY geo /app/geo
COPY simulation /app/simulation
COPY ml /app/ml
COPY scripts /app/scripts
COPY backend /app/backend

# datasets/ and data/ are mounted as volumes (see docker-compose.yml) - never baked into the image.
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
