FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget unzip curl gnupg ca-certificates fonts-liberation \
    libnss3 libxss1 libappindicator3-1 libasound2 libatk-bridge2.0-0 libgtk-3-0 libx11-xcb1 \
    chromium chromium-driver \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set environment variables for Chrome and Chromedriver binaries
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
