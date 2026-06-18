FROM python:3.11-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8200
CMD ["uvicorn", "app.collector:app", "--host", "0.0.0.0", "--port", "8200"]
