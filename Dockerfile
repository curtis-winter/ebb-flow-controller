FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt tzdata

RUN pip install --no-cache-dir "git+https://github.com/python-kasa/python-kasa.git@refs/pull/1625/head" --no-deps --force-reinstall

COPY backend/ ./backend/
COPY frontend/ ./frontend/

ENV PYTHONUNBUFFERED=1

EXPOSE 9731

CMD ["gunicorn", "--bind", "0.0.0.0:9731", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "backend.app:app"]