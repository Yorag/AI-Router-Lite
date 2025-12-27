FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY static/ ./static/

# Copy config file and entrypoint
COPY config.example.json ./config.json
COPY entrypoint.sh .

# Setup permissions and data directory
RUN chmod +x entrypoint.sh && mkdir -p /app/data

# Expose port
EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
