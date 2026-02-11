# Document Processor Service
# Story 2.4 - Task 5

FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy consumer stub
COPY consumer_stub.py .

# Run consumer
CMD ["python", "consumer_stub.py"]
