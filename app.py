from flask import Flask, jsonify, request, send_file
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import subprocess
import os
import traceback
import time
import logging
from io import BytesIO
import base64

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
)

file_handler = logging.FileHandler("app.log")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(file_handler)

ADMIN_CODE = "ICU14CU"

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

app = Flask(__name__)

chrome_bin = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
chromedriver_bin = os.environ.get("CHROMEDRIVER_BIN", "/usr/bin/chromedriver")

options = Options()
options.binary_location = chrome_bin
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument(f"user-agent={user_agent}")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--disable-software-rasterizer")

service = Service(chromedriver_bin)
driver = webdriver.Chrome(service=service, options=options)

def take_screenshot_in_memory(driver):
    try:
        logging.info("\U0001f4f8 Capturing full-page screenshot using CDP...")
        metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        width = metrics["contentSize"]["width"]
        height = metrics["contentSize"]["height"]
        driver.set_window_size(width, height)
        screenshot_data = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "fromSurface": True,
            "captureBeyondViewport": True
        })
        screenshot_png = base64.b64decode(screenshot_data["data"])
        return screenshot_png
    except Exception as e:
        logging.error("❌ Failed to capture full-page screenshot", exc_info=True)
        raise

def get_binary_version(binary_path):
    try:
        result = subprocess.run([binary_path, "--version"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        logging.error(f"❌ Could not determine version for {binary_path}", exc_info=True)
        return f"Could not determine version: {e}"

def dismiss_popup(timeout=7):
    logging.info("🔍 Looking for 'Stay logged out' popup...")
    try:
        for i in range(timeout):
            logging.debug(f"⌛ Popup check attempt {i+1}")
            result = driver.execute_script("""
                const logoutLink = Array.from(document.querySelectorAll('a, button')).find(el =>
                    el.textContent.trim() === "Stay logged out"
                );
                if (logoutLink) { logoutLink.click(); return true; }
                return false;
            """)
            if result:
                logging.info(f"🎉 'Stay logged out' popup found and clicked (after {i+1}s).")
                time.sleep(2)
                return True
            time.sleep(1)
        logging.warning("⏱ No 'Stay logged out' popup detected after timeout.")
        return False
    except Exception as e:
        logging.error("❌ Failed during popup dismissal", exc_info=True)
        return False

setup_complete = False

def setup_chatgpt_session():
    global setup_complete
    if setup_complete:
        logging.info("🔁 ChatGPT setup already completed, skipping re-init.")
        return
    logging.info("🌐 Starting navigation to ChatGPT homepage.")
    try:
        driver.get("https://chatgpt.com")
        logging.debug("⏳ Waiting for the page to fully load...")
        time.sleep(15)
        for i in range(3):
            logging.debug(f"🔄 Attempt #{i+1} to dismiss popup.")
            if dismiss_popup(timeout=10):
                logging.info("✅ Popup dismissed successfully.")
                break
            time.sleep(5)
        take_screenshot_in_memory(driver)
        setup_complete = True
        logging.info("✅ ChatGPT setup completed.")
    except Exception as e:
        logging.error("❌ Error during initial ChatGPT setup", exc_info=True)
        raise

def wait_for_response_js():
    js_script = """
        var callback = arguments[arguments.length - 1];
        const maxWaitTime = 20000;
        const intervalTime = 500;
        const startTime = Date.now();

        function checkResponse() {
            const assistantMessages = Array.from(document.querySelectorAll('div[data-message-author-role="assistant"]'));
            if (assistantMessages.length > 0) {
                const last = assistantMessages.at(-1);
                const markdown = last.querySelector('div.markdown');
                if (markdown && markdown.innerText.trim()) {
                    callback(markdown.innerText.trim());
                    return;
                }
            }
            if (Date.now() - startTime > maxWaitTime) {
                callback(null);
            } else {
                setTimeout(checkResponse, intervalTime);
            }
        }

        checkResponse();
    """
    return driver.execute_async_script(js_script)



@app.route('/ask')
def ask():
    global setup_complete
    try:
        query = request.args.get("q")
        if not query:
            logging.warning("⚠️ Received request without query parameter.")
            return jsonify({"error": "No query provided"}), 400

        logging.info(f"🔐 Received query: {query}")
        logging.info("✅ Session is ready")

        
        logging.info("💬 Typing and sending query...")
        

        typing_script = """
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
            if (!editor) return;

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
            if (sendBtn) sendBtn.click();
        })();
        """
        driver.execute_script(typing_script, query)

        time.sleep(1)  # Give the UI a moment to react
        logging.info("📨 Query sent, waiting for response...")
      

        response = wait_for_response_js()

        if response:
            logging.debug(f"🧠 Bot response: {response}")
            logging.info("✅ Response received")
            return jsonify({"bot": response})
            take_screenshot_in_memory(driver)
        else:
            logging.warning("⚠️ No response found within timeout")
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
        logging.warning("🚫 Unauthorized restart attempt.")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        logging.info("♻️ Restart request received.")
        if driver:
            logging.info("🧹 Quitting existing driver session...")
            driver.quit()
        driver = webdriver.Chrome(service=service, options=options)
        setup_chatgpt_session()
        logging.info("✅ Browser session restarted.")
        return jsonify({"status": "success", "message": "Browser session restarted."})
    except Exception as e:
        logging.error("❌ Failed to restart browser", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/screenshot")
def serve_screenshot_api():
    try:
        screenshot_png = take_screenshot_in_memory(driver)
        logging.info("✅ Screenshot served as PNG.")
        return send_file(
            BytesIO(screenshot_png),
            mimetype="image/png",
            as_attachment=False,
            download_name="screenshot.png"
        )
    except Exception as e:
        logging.error("❌ Failed to serve screenshot", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    chrome_version = get_binary_version(chrome_bin)
    chromedriver_version = get_binary_version(chromedriver_bin)
    logging.info(f"🧪 Chromium version: {chrome_version}")
    logging.info(f"🧪 Chromedriver version: {chromedriver_version}")
    setup_chatgpt_session()
    logging.info("🚀 Starting Flask app on port 10000")
    app.run(host='0.0.0.0', port=10000, debug=False)
