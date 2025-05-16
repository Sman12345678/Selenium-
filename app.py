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
    """Attempt to dismiss 'Stay logged out' popup if it appears."""
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

        # Silently continue if popup never appeared
        return False

    except Exception as e:
        logging.error(f"❌ Unexpected error in dismiss_popup: {e}")
        return False

setup_complete = False

def setup_chatgpt_session():
    global setup_complete
    if setup_complete:
        return

    logging.info("🌐 Navigating to ChatGPT")
    driver.get("https://chatgpt.com")
    time.sleep(15)  # Wait for full page load

    for _ in range(3):
        if dismiss_popup(timeout=10):
            break
        time.sleep(5)

    setup_complete = True
    logging.info("✅ Initial setup completed")

def wait_for_response(max_wait_time=10, interval=1):
    """Polls for the last bot response using partial class match in JavaScript"""
    js_script = """
        const allDivs = document.querySelectorAll('div');
        const matching = [...allDivs].filter(div => {
            const classes = div.className.split(/\\s+/);
            return classes.includes('markdown') &&
                   classes.includes('prose') &&
                   classes.includes('dark:prose-invert') &&
                   classes.includes('w-full') &&
                   classes.includes('break-words') &&
                   classes.includes('light');
        });

        if (matching.length > 0) {
            return matching[matching.length - 1].textContent.trim();
        } else {
            return null;
        }
    """

    for _ in range(max_wait_time):
        response = driver.execute_script(js_script)
        if response:
            return response
        time.sleep(interval)

    return None

@app.route('/ask')
def ask():
    global setup_complete

    try:
        query = request.args.get("q")
        if not query:
            return jsonify({"error": "No query provided"}), 400

        setup_chatgpt_session()  # Ensure session setup
        
        #dismiss popup before pasting query....
        dismiss_popup()

        # Use JavaScript to simulate typing and sending
        script = """
        (async () => {
            const text = arguments[0];

            // Dismiss popup if it appears
            const logoutLink = Array.from(document.querySelectorAll('a, button')).find(
                el => el.textContent.trim() === "Stay logged out"
            );
            if (logoutLink) {
                logoutLink.click();
                await new Promise(resolve => setTimeout(resolve, 1000));
            }

            // Find the editor
            const editor = document.querySelector('[contenteditable="true"].ProseMirror');
            if (!editor) {
                console.error("❌ Editor not found");
                return;
            }

            editor.focus();

            // Simulate typing
            for (const char of text) {
                editor.dispatchEvent(new InputEvent('beforeinput', {
                    inputType: 'insertText',
                    data: char,
                    bubbles: true,
                    cancelable: true
                }));
                document.execCommand('insertText', false, char);
                await new Promise(resolve => setTimeout(resolve, 30));
            }

            // Click the send button
            const sendBtn = document.querySelector('#composer-submit-button');
            if (sendBtn) {
                sendBtn.click();
            } else {
                console.warn("⚠️ Send button not found");
            }
        })();
        """
        driver.execute_script(script, query)
        logging.info("✍️ Box Found, Typing.....")

        # Wait before polling for response
        time.sleep(1)

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
