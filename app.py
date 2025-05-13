from flask import Flask, jsonify, request
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
import subprocess
import os
import traceback
import time
from bs4 import BeautifulSoup
import logging
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Set up basic logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


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

def dismiss_popup(timeout=2):
    try:
        logging.info("Attempting to bypass popup")
        WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                ".text-token-text-secondary.mt-5.cursor-pointer.text-sm.font-semibold.underline"
            ))
        ).click()
        logging.info("Popup bypassed successfully")
        time.sleep(1)
    except Exception:
        logging.debug("No popup to bypass")
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
        driver.get("https://chatgpt.com")
        time.sleep(5)

        # Check and click the popup right after page load if it appears
        dismiss_popup()

        # Wait for the page to load, then click the popup repeatedly if it shows
        start_time = time.time()
        timeout = 10
        while time.time() - start_time < timeout:
            time.sleep(0.5)
            dismiss_popup()  # Check periodically during the timeout

        if query:
            try:
                # Type the query into the ProseMirror editor
                editor = driver.find_element(By.ID, "prompt-textarea")
                editor.send_keys(query)
                logging.info("👉 passing query to box")


                # Click the send button
                send_button = driver.find_element(By.ID, "composer-submit-button")
                send_button.click()
                logging.info("🕵️ hitting  send button")
            except NoSuchElementException:
                return jsonify({"error": "Input field or send button not found"}), 400
        else:
            return jsonify({"error": "No query provided"}), 400

        # Wait for a response to load
        time.sleep(6)
    

        # After submitting, check and click the popup again if it reappears
        dismiss_popup()

        page = driver.page_source
        soup = BeautifulSoup(page, 'html.parser')

        # Extract the paragraph from the updated div
        div = soup.find("div", class_="markdown prose dark:prose-invert w-full break-words dark")

        if div:
            p = div.find("p")
            if p:
                logging.info("✅ response sent successfully")
                return jsonify({"bot": p.text})
            else:
                return jsonify({"error": "Paragraph not found"}), 404
        else:
            return jsonify({"error": "Target div not found"}), 404

    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
        logging.error(str(e))


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
