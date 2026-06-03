FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./signal_engine ./signal_engine
COPY .env .env

EXPOSE 8000 9001

CMD ["python", "-m", "signal_engine.main"]