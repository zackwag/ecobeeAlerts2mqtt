FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ecobee_alerts_2_mqtt/ .

VOLUME ["/data"]

CMD ["python", "main.py"]
