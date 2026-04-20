FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# Install python deps first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r /app/requirements.txt

# Copy service code
COPY . /app

EXPOSE 8590

# Run the websocket service
CMD ["python", "websocket.py"]