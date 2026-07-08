FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /tmp/worker-requirements.txt
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir \
    -r /tmp/worker-requirements.txt \
    -r /tmp/backend-requirements.txt

COPY worker/ /app/
COPY backend/ /backend/
ENV PYTHONPATH=/app:/backend

RUN useradd -m worker && chown -R worker:worker /app
USER worker

CMD ["celery", "-A", "celery_app", "worker", "-Q", "high,normal,low", "--concurrency=4", "--loglevel=info"]