from flask import Flask, jsonify, request, send_file
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

setup_complete = False

ADMIN_CODE="ICU14CU"  #FOR SERVER RESTART

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"

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
options.add_argument(f"user-agent={user_agent}")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--remote-debugging-port=9222")
options.add_argument("--disable-gpu")
options.add_argument("--disable-software-rasterizer")

service = Service(chromedriver_bin)
driver = webdriver.Chrome(service=service, options=options)

def dismiss_popup(timeout=15):
    logging.info("🔍 Checking for 'Stay logged out' popup...")
    try:
        for i in range(timeout):
            result = driver.execute_script("""
                const logoutLink = Array.from(document.querySelectorAll('a, button')).find(el =>
                  el.textContent.trim() === "Stay logged out"
                );
                if (logoutLink) { logoutLink.click(); return true; }
                return false;
            """)
            if result:
                logging.info(f"🎉 Popup dismissed at second {i+1}")
                time.sleep(2)
                return True
            time.sleep(1)
        logging.info("✅ No popup appeared during timeout window")
        return False
    except Exception as e:
        logging.error(f"❌ Error dismissing popup: {e}")
        return False

def setup_chatgpt_session():
    global setup_complete
    if setup_complete:
        return
    logging.info("🌐 Navigating to ChatGPT")
    driver.get("https://chatgpt.com")
    time.sleep(15)
    for _ in range(3):
        if dismiss_popup(timeout=10):
            break
        time.sleep(5)
    setup_complete = True
    logging.info("✅ Initial setup completed")

def wait_for_response(max_wait_time=30, interval=3):
    logging.info("⏳ Polling for bot response...")
    driver.save_screenshot("image.png")
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
    for i in range(max_wait_time):
        try:
            response = driver.execute_script(js_script)
            if response:
                logging.info(f"✅ Response found on attempt {i+1}")
                return response
            else:
                logging.debug(f"⌛ No response found (attempt {i+1})")
        except Exception as e:
            logging.error(f"❌ JS execution failed: {e}")
        time.sleep(interval)
    logging.warning("⚠️ No response found within max wait time")
    return None

@app.route('/ask')
def ask():
    global setup_complete
    try:
        query = request.args.get("q")
        if not query:
            return jsonify({"error": "No query provided"}), 400

        logging.info(f"🔐 Received query: {query}")
        setup_chatgpt_session()
        logging.info("✅ Session is ready")

        dismiss_popup()
        logging.info("💬 Typing and sending query...")
        driver.save_screenshot("image.png")

        script = """
        (async () => {
            const text = arguments[0];
            const logoutLink = Array.from(document.querySelectorAll('a, button')).find(
                el => el.textContent.trim() === "Stay logged out"
            );
            if (logoutLink) {
                logoutLink.click();
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
            const editor = document.querySelector('[contenteditable="true"].ProseMirror');
            if (!editor) {
                console.error("❌ Editor not found");
                return;
            }
            editor.focus();
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
            const sendBtn = document.querySelector('#composer-submit-button');
            if (sendBtn) {
                sendBtn.click();
            } else {
                console.warn("⚠️ Send button not found");
            }
        })();
        """
        driver.execute_script(script, query)

        time.sleep(1)
        logging.info("📨 Query sent, waiting for response...")
        driver.save_screenshot("image.png")
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

@app.route('/restart')
def restart_browser():
    global driver
    code = request.args.get("code")
    if code != ADMIN_CODE:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        if driver:
            driver.quit()
        driver = webdriver.Chrome(service=service, options=options)
        setup_chatgpt_session()
        return jsonify({"status": "success", "message": "Browser session restarted."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/screenshot')
def screenshot():
    path = "image.png"  # or just "screenshot.png" if you want a generic one
    try:
        return send_file(path, mimetype='image/png')
    except Exception as e:
        return jsonify({"error": f"Could not retrieve screenshot: {e}"}), 500


if __name__ == '__main__':
    print("Chromium version:", get_binary_version(chrome_bin))
    print("Chromedriver version:", get_binary_version(chromedriver_bin))
    app.run(host='0.0.0.0', port=10000)
