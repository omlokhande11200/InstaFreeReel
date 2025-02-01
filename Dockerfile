# Use Debian as the base image (Tor is available)
FROM debian:latest

# Install Tor and required packages
RUN apt-get update && apt-get install -y tor python3 python3-pip && \
    pip install --no-cache-dir -r requirements.txt

# Set working directory
WORKDIR /app
COPY . .

# Expose Flask API port
EXPOSE 5000

# Start Tor and Flask API
CMD tor & gunicorn app:app --timeout 300
