FROM python:3.12-slim

WORKDIR /bot
COPY . .
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "uvicorn", "scripts.secure_app:app", "--host", "0.0.0.0", "--port", "5000"]
