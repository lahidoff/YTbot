# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта (кроме certs.json, его добавим позже)
COPY bot.py .

# Указываем команду для запуска бота
CMD ["python", "bot.py"]