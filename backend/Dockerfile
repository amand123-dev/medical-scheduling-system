FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "for i in 1 2 3; do alembic upgrade head && break || sleep 5; done && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
