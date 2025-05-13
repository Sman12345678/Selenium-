from flask import Flask, jsonify, request
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
import subprocess
import os
import traceback
import time
from bs4 import BeautifulSoup
import logging
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading

# Set up basic logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
wait = WebDriverWait(driver, 10)

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

def dismiss_popup(timeout=1):
    try:
        WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                ".text-token-text-secondary.mt-5.cursor-pointer.text-sm.font-semibold.underline"
            ))
        ).click()
        logging.info("🎉 Popup found and dismissed")
        time.sleep(1)  # Let DOM update after dismiss
    except TimeoutException:
        # Popup not found within timeout, no need to log this
        pass
    except Exception as e:
        logging.warning(f"Unexpected error in dismiss_popup: {e}")


def popup_watcher():
    while True:
        try:
            dismiss_popup(timeout=1)
        except Exception:
            pass
        time.sleep(1)  # Check once per second

@app.route('/ask')
def ask():
    try:
        query = request.args.get("q")
        driver.get("https://chaklo.com")
        time.sleep(5)

        # Attempt to dismiss popup once after loading
        dismiss_popup()

        if not query:
            return jsonify({"error": "No query provided"}), 400

        # Locate input field
        try:
            editor = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div#prompt-textarea.ProseMirror[contenteditable='true']")))
            editor.send_keys(query)
            logging.info("✅ Query typed into input box")
        except NoSuchElementException:
            return jsonify({"error": "Input field not found"}), 400

        # Locate and click send button
        try:
            send_button = driver.find_element(By.ID, "composer-submit-button")
            send_button.click()
            logging.info("✅ Send button clicked")
        except NoSuchElementException:
            return jsonify({"error": "Send button not found"}), 400

        # Wait for response to load
        time.sleep(6)
        dismiss_popup()

        # Parse response
        page = driver.page_source
        soup = BeautifulSoup(page, 'html.parser')

        div = soup.find("div", class_="markdown prose dark:prose-invert w-full break-words dark")
        if div:
            all_text = div.get_text(separator="\n").strip()
            if all_text:
                logging.info("✅ Response extracted successfully")
                return jsonify({"bot": all_text})
            else:
                return jsonify({"error": "Response div found, but it's empty"}), 404
        else:
            return jsonify({"error": "Response container not found"}), 404

    except Exception as e:
        logging.error(str(e))
        return jsonify({
            "error": "Unexpected server error",
            "details": str(e),
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
    threading.Thread(target=popup_watcher, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
