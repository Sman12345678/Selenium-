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
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

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
        logging.info("📸 Capturing full-page screenshot using CDP...")
        metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        width = metrics["contentSize"]["width"]
        height = metrics["contentSize"]["height"]
        
        # Set the viewport to full height
        driver.set_window_size(width, height)
        
        screenshot_data = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "fromSurface": True,
            "captureBeyondViewport": True
        })
        screenshot_png = base64.b64decode(screenshot_data["data"])
        return screenshot_png
    except Exception as e:
        logging.error(f"❌ Failed to capture full-page screenshot: {e}")
        raise

def get_binary_version(binary_path):
    try:
        result = subprocess.run([binary_path, "--version"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Could not determine version: {e}"

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

setup_complete = False

def setup_chatgpt_session():
    global setup_complete
    if setup_complete:
        return
    logging.info("🌐 Navigating to Chatgpt")
    driver.get("https://chatgpt.com")
   
    time.sleep(15)
    for _ in range(3):
        if dismiss_popup(timeout=10):
            break
        time.sleep(5)
    setup_complete = True
    take_screenshot_in_memory(driver)
    logging.info("✅ Initial setup completed")

def wait_for_response_js():
    js_script = """
        var callback = arguments[arguments.length - 1];

        (function check() {
            const maxWaitTime = 20000;
            const intervalTime = 500;
            const startTime = Date.now();

            function poll(resolve) {
                const targetDiv = document.querySelector('div.markdown.prose.dark\\:prose-invert.w-full.break-words.dark');
                if (targetDiv) {
                    const paragraphs = targetDiv.querySelectorAll('p');
                    if (paragraphs.length > 0) {
                        resolve(paragraphs[paragraphs.length - 1].innerText.trim());
                        return;
                    }
                }

                if (Date.now() - startTime > maxWaitTime) {
                    resolve(null);
                    return;
                }

                setTimeout(() => poll(resolve), intervalTime);
            }

            new Promise(poll).then(callback);
        })();
    """
    return driver.execute_async_script(js_script)

   

@app.route('/ask')
def ask():
    global setup_complete
    try:
        query = request.args.get("q")
        if not query:
            return jsonify({"error": "No query provided"}), 400

        logging.info(f"🔐 Received query: {query}")
        
        logging.info("✅ Session is ready")

        dismiss_popup()
        logging.info("💬 Typing and sending query...")
        take_screenshot_in_memory(driver)

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

        time.sleep(1)  # Small wait to allow send action to trigger

        logging.info("📨 Query sent, waiting for response...")
        take_screenshot_in_memory(driver)
        response = wait_for_response_js()

        if response:
            logging.info("✅ Response received")
            return jsonify({"bot": response})
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
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        if driver:
            driver.quit()
        driver = webdriver.Chrome(service=service, options=options)
        setup_chatgpt_session()
        return jsonify({"status": "success", "message": "Browser session restarted."})
    except Exception as e:
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
        logging.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    print("Chromium version:", get_binary_version(chrome_bin))
    print("Chromedriver version:", get_binary_version(chromedriver_bin))
    setup_chatgpt_session()
    print("""
      _____ _    _ _      ______ _____ _____ __  __          _   _ 
 / ____| |  | | |    |  ____|_   _|_   _|  \/  |   /\   | \ | |
| (___ | |  | | |    | |__    | |   | | | \  / |  /  \  |  \| |
 \___ \| |  | | |    |  __|   | |   | | | |\/| | / /\ \ | . ` |
 ____) | |__| | |____| |____ _| |_ _| |_| |  | |/ ____ \| |\  |
|_____/ \____/|______|______|_____|_____|_|  |_/_/    \_\_| \_|
                                                              
""")
    app.run(host='0.0.0.0', port=10000,debug=True)
   
