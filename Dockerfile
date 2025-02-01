# Use Debian as the base image
FROM debian:latest

# Install dependencies, including Tor, Python, and pip
RUN apt-get update && apt-get install -y tor python3 python3-pip python3-venv

# Set up a virtual environment and install dependencies inside it
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Set working directory
WORKDIR /app
COPY . .

# Install Python dependencies inside the virtual environment
RUN pip install -r requirements.txt

# Expose the necessary port
EXPOSE 5000

# Start Tor and then run the Flask API
CMD tor & gunicorn app:app --timeout 300
