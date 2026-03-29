FROM python:3.11-slim

WORKDIR /app

# Install system deps for google-auth and other native packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run sets PORT env var; default to 8080
ENV PORT=8080
ENV HOST=0.0.0.0

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080"]
