# Compile the React frontend once; the runtime image contains no Node tooling.
FROM node:24-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Python slim is sufficient: PyMuPDF and python-pptx install pre-built wheels.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/tmp/papertoppt

# Hugging Face runs Docker Spaces as UID 1000. Creating that user and assigning
# ownership at COPY time avoids runtime permission failures.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /home/appuser/app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=appuser:appuser backend/ ./backend/
COPY --from=frontend-build --chown=appuser:appuser /build/frontend/dist ./frontend/dist
RUN mkdir --parents /tmp/papertoppt && chown appuser:appuser /tmp/papertoppt

USER appuser
EXPOSE 7860

# One worker is deliberate: job status is held in process memory and the API
# uses FastAPI background tasks. Scale this only after adding shared job state.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "7860"]
