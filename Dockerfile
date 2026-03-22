FROM python:3.11-slim

# Устанавливаем DNS для правильного резолвинга
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 8.8.4.4" >> /etc/resolv.conf

WORKDIR /app

# Устанавливаем зависимости системы
RUN apt-get update && apt-get install -y \
    curl \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Проверяем доступ к Telegram API
RUN echo "=== Проверка сети ===" && \
    nslookup api.telegram.org && \
    curl -I --connect-timeout 10 https://api.telegram.org || echo "⚠️ Нет доступа к Telegram API"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/app/data
RUN mkdir -p /app/data && chmod 777 /app/data

CMD ["python", "main.py"]
