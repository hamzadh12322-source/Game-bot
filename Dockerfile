FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV DB_PATH=/data/database.db
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
