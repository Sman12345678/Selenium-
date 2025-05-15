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

class PersistentPopupError(Exception):
    """Raised when popup cannot be dismissed after several attempts."""
    pass

def dismiss_popup(timeout=15):
    try:
        for _ in range(timeout):
            result = driver.execute_script("""
                const logoutLink = Array.from(document.querySelectorAll('a, button')).find(el =>
                  el.textContent.trim() === "Stay logged out"
                );
                if (logoutLink) { logoutLink.click(); return true; }
                return false;
            """)
            if result:
                logging.info("🎉 Popup found and dismissed via JS")
                time.sleep(2)  # Let DOM update
                return True
            time.sleep(1)

        logging.warning(f"⚠️ 'Stay logged out' not found within timeout ({timeout}s)")
        return False

    except Exception as e:
        logging.error(f"❌ Unexpected error in dismiss_popup: {e}")
        return False


def popup_watcher(max_retries=30):
    """Continuously tries to dismiss a popup for a maximum number of retries."""
    logging.info("🔍 Starting popup watcher...")
    retries = 0
    while retries < max_retries:
        success = dismiss_popup(timeout=15)
        if success:
            logging.info("✅ Popup dismissed by popup_watcher")
            return True
        retries += 1
        time.sleep(1)
    
    # If we exhaust all retries, raise the PersistentPopupError
    logging.error(f"🚨 Popup could not be dismissed after {max_retries} retries")
    raise PersistentPopupError("Popup could not be dismissed after multiple attempts.")

setup_complete = False

# Start the background watcher
threading.Thread(target=popup_watcher, daemon=True).start()

def setup_chatgpt_session():
    global setup_complete
    if setup_complete:
        return

    logging.info("🌐 Navigating to ChatGPT")
    driver.get("https://chatgpt.com")
    time.sleep(15)  # Wait for full page load

    popup_dismissed = False
    for attempt in range(3):
        if dismiss_popup(timeout=10):
            popup_dismissed = True
            break
        time.sleep(5)

    if not popup_dismissed:
        logging.warning("⚠️ Popup was not found/dismissed during setup. Background watcher is running.")


    setup_complete = True
    logging.info("✅ Initial setup completed")
def wait_for_response(max_wait_time=10, interval=1):
    """ Polls for the response div to appear within max_wait_time seconds """
    for _ in range(max_wait_time):
        try:
            # Check if the response element is present
            page = driver.page_source
            soup = BeautifulSoup(page, 'html.parser')
            div = soup.find("div", class_="markdown prose dark:prose-invert w-full break-words dark")
            if div:
                return div.get_text(separator="\n").strip()  # Return the text if found
        except Exception as e:
            logging.error("❌ Error during polling: " + str(e))
        
        # Wait for the next polling interval
        time.sleep(interval)
    
    # If we reach this point, the response wasn't found in the maximum wait time
    return None
@app.route('/ask')
def ask():
    global setup_complete

    try:
        query = request.args.get("q")
        if not query:
            return jsonify({"error": "No query provided"}), 400

        setup_chatgpt_session()  # Ensure session setup

        # Focus and type into the ProseMirror editor
        editor = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "prompt-textarea"))
        )

        # Use JavaScript to simulate typing (async IIFE pattern)
        script = """
            const editor = arguments[0];
            editor.focus();
            const text = arguments[1];

            (async function() {
                for (let char of text) {
                    editor.dispatchEvent(new KeyboardEvent('keydown', { key: char }));
                    editor.dispatchEvent(new InputEvent('beforeinput', {
                        inputType: 'insertText',
                        data: char,
                        bubbles: true,
                        cancelable: true
                    }));
                    document.execCommand('insertText', false, char);
                    await new Promise(resolve => setTimeout(resolve, 30));
                }
            })();
        """
        driver.execute_script(script, editor, query)

        # Wait briefly before sending
        time.sleep(1)

        # Click the send button
        try:
            send_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "composer-submit-button"))
            )
            send_button.click()
            logging.info("✅ Send button clicked")
        except NoSuchElementException:
            return jsonify({"error": "Send button not found"}), 400

        # Poll for response with dynamic waiting
        response = wait_for_response(max_wait_time=15, interval=2)

        if response:
            return jsonify({"bot": response})
        else:
            return jsonify({"error": "Response not found within the expected time."}), 404

    except Exception as e:
        logging.error("❌ Error in /ask endpoint", exc_info=True)
        return jsonify({
            "error": "Unexpected server error",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500
if __name__ == '__main__':
    print("Chromium version:", get_binary_version(chrome_bin))
    print("Chromedriver version:", get_binary_version(chromedriver_bin))
    app.run(host='0.0.0.0', port=10000)
