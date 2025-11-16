FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app
COPY . /app

# Expose port
EXPOSE ${PORT}

# Use gunicorn; Vercel sets $PORT environment variable at runtime
CMD ["sh", "-lc", "gunicorn app:app -b 0.0.0.0:${PORT} --workers 1"]
