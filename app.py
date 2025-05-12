from flask import Flask, jsonify, request
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import subprocess
import os
import traceback
import time
from bs4 import BeautifulSoup

app = Flask(__name__)

def get_binary_version(binary_path):
    try:
        result = subprocess.run([binary_path, "--version"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Could not determine version: {e}"

chrome_bin = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
chromedriver_bin = os.environ.get("CHROMEDRIVER_BIN", "/usr/bin/chromedriver")

options = Options()
options.binary_location = chrome_bin
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--remote-debugging-port=9222")
options.add_argument("--disable-gpu")
options.add_argument("--disable-software-rasterizer")

service = Service(chromedriver_bin)
driver = webdriver.Chrome(service=service, options=options)

@app.route('/')
def index():
    try:
        query = request.args.get("query")
        driver.get("https://chat-with-kora.onrender.com/Kora.html")

        if query:
            # Wait for the input box to be present
            time.sleep(2)  # May adjust with WebDriverWait for production use
            input_box = driver.find_element(By.NAME, "input-field")
            input_box.clear()
            input_box.send_keys(query)
            input_box.send_keys(Keys.RETURN)

            # Wait for the response to appear (adjust time as needed)
            time.sleep(10)
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")

            # Look for the latest bot message
            messages = soup.select('.bot .message')
            if messages:
                ai_response = messages[-1].get_text(strip=True)
            else:
                ai_response = "Could not find AI response in page."

            return jsonify({"query": query, "ai_response": ai_response})

        else:
            # If no query, just return the page title
            title = driver.title
            return jsonify({"title": title})

    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

@app.route('/quit')
def quit_browser():
    global driver
    try:
        if driver:
            driver.quit()
            driver = None
            return jsonify({"message": "Browser session quit."})
        else:
            return jsonify({"message": "No active browser session."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Chromium version:", get_binary_version(chrome_bin))
    print("Chromedriver version:", get_binary_version(chromedriver_bin))
    app.run(host='0.0.0.0', port=10000)
