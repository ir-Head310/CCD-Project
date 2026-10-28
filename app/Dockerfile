FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py catalog.py ./

RUN useradd --uid 10001 --no-create-home appuser
USER 10001

EXPOSE 8080
# One sync worker per pod: each pod gets a small CPU limit, so scaling happens by
# adding pods (HPA) rather than by adding workers inside a pod.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 30 --access-logfile - app:app"]
