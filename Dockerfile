FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .  # Эта строка копирует все файлы, включая certs.json
CMD ["python", "bot.py"]
