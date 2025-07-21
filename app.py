
from flask import Flask, jsonify, request, send_file, render_template
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import subprocess
import os
import traceback
import time
import logging
from io import BytesIO
import base64
from PIL import Image
import json
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
)

file_handler = logging.FileHandler("app.log")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(file_handler)

ADMIN_CODE = "ICU14CU"
MAX_RETRIES = 3
REQUEST_TIMEOUT = 120
RESPONSE_TIMEOUT = 90

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

app = Flask(__name__)

chrome_bin = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
chromedriver_bin = os.environ.get("CHROMEDRIVER_BIN", "/usr/bin/chromedriver")

# Enhanced Chrome options
options = Options()
options.binary_location = chrome_bin
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--disable-software-rasterizer")
options.add_argument("--disable-extensions")
options.add_argument("--disable-plugins")
options.add_argument("--disable-images")  # Speed up loading
options.add_argument("--disable-javascript-harmony")
options.add_argument("--disable-web-security")
options.add_argument("--disable-features=TranslateUI")
options.add_argument("--disable-ipc-flooding-protection")
options.add_argument(f"--user-agent={user_agent}")
options.add_argument("--window-size=1920,1080")

# Performance optimizations
prefs = {
    "profile.default_content_setting_values": {
        "notifications": 2,
        "media_stream": 2,
        "geolocation": 2
    },
    "profile.managed_default_content_settings": {
        "images": 2
    }
}
options.add_experimental_option("prefs", prefs)

service = Service(chromedriver_bin)
driver = None
setup_complete = False
last_activity = None

def initialize_driver():
    """Initialize Chrome driver with error handling"""
    global driver
    try:
        if driver:
            driver.quit()
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(10)
        return True
    except Exception as e:
        logging.error("❌ Failed to initialize driver", exc_info=True)
        return False

def get_binary_version(binary_path):
    """Get version of Chrome/ChromeDriver binary"""
    try:
        result = subprocess.run([binary_path, "--version"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        logging.error(f"❌ Could not determine version for {binary_path}", exc_info=True)
        return f"Could not determine version: {e}"

def take_screenshot_in_memory(driver):
    """Take full page screenshot"""
    try:
        logging.info("📸 Capturing screenshot")
        
        # Get viewport dimensions
        viewport_width = driver.execute_script("return window.innerWidth")
        viewport_height = driver.execute_script("return window.innerHeight")
        
        # Get full page height
        total_height = driver.execute_script("""
            return Math.max(
                document.body.scrollHeight,
                document.body.offsetHeight,
                document.documentElement.clientHeight,
                document.documentElement.scrollHeight,
                document.documentElement.offsetHeight
            );
        """)
        
        # Add buffer for floating elements
        total_height = min(total_height + 200, 32767)  # Limit to prevent errors
        
        # Set window size for full capture
        driver.set_window_size(viewport_width, total_height)
        time.sleep(2)
        
        # Take screenshot using CDP
        screenshot_data = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
            "clip": {
                "width": viewport_width,
                "height": total_height,
                "x": 0,
                "y": 0,
                "scale": 1
            }
        })

        screenshot_png = base64.b64decode(screenshot_data["data"])
        logging.info(f"✅ Screenshot captured ({viewport_width}x{total_height}px)")
        return screenshot_png
        
    except Exception as e:
        logging.error("❌ Screenshot capture failed", exc_info=True)
        # Fallback to regular screenshot
        try:
            screenshot_png = driver.get_screenshot_as_png()
            logging.info("✅ Fallback screenshot captured")
            return screenshot_png
        except:
            raise e

def dismiss_popups(timeout=10):
    """Dismiss various popups that might appear"""
    logging.info("🔍 Checking for popups to dismiss...")
    
    dismiss_script = """
    let dismissed = false;
    const popupSelectors = [
        // Stay logged out popup
        'a[href*="logout"]',
        'button:contains("Stay logged out")',
        'a:contains("Stay logged out")',
        
        // Modal close buttons
        '[data-testid*="close"]',
        '.modal button[aria-label="Close"]',
        'button[aria-label="Close"]',
        
        // Cookie banners
        'button:contains("Accept")',
        'button:contains("OK")',
        
        // Other common popups
        '[role="dialog"] button',
        '.popup button',
        '.overlay button'
    ];
    
    // Try text-based selectors
    const textSelectors = [
        "Stay logged out",
        "Accept all",
        "Continue",
        "Got it",
        "OK",
        "Close"
    ];
    
    for (const text of textSelectors) {
        const elements = Array.from(document.querySelectorAll('button, a, [role="button"]'))
            .filter(el => el.textContent.trim().toLowerCase().includes(text.toLowerCase()));
        
        for (const el of elements) {
            if (el.offsetParent !== null) { // Check if visible
                el.click();
                dismissed = true;
                break;
            }
        }
        if (dismissed) break;
    }
    
    // Try selector-based dismissal
    if (!dismissed) {
        for (const selector of popupSelectors) {
            try {
                const element = document.querySelector(selector);
                if (element && element.offsetParent !== null) {
                    element.click();
                    dismissed = true;
                    break;
                }
            } catch (e) { /* ignore */ }
        }
    }
    
    return dismissed;
    """
    
    try:
        for attempt in range(3):
            dismissed = driver.execute_script(dismiss_script)
            if dismissed:
                logging.info(f"✅ Popup dismissed on attempt {attempt + 1}")
                time.sleep(2)
                return True
            time.sleep(2)
        
        logging.info("ℹ️ No popups found to dismiss")
        return False
        
    except Exception as e:
        logging.error("❌ Error while dismissing popups", exc_info=True)
        return False

def check_session_health():
    """Check if the current session is healthy"""
    try:
        # Test basic page interaction
        title = driver.title
        url = driver.current_url
        
        # Check if we're still on ChatGPT
        if "chatgpt.com" not in url.lower():
            logging.warning(f"⚠️ Not on ChatGPT page: {url}")
            return False
            
        # Check if page is responsive
        driver.execute_script("return document.readyState;")
        
        # Look for chat interface elements
        has_input = driver.execute_script("""
            const selectors = [
                '[contenteditable="true"]',
                'textarea',
                '#prompt-textarea',
                '[data-testid="textbox"]'
            ];
            return selectors.some(sel => document.querySelector(sel) !== null);
        """)
        
        if not has_input:
            logging.warning("⚠️ No input element found")
            return False
            
        logging.info("✅ Session health check passed")
        return True
        
    except Exception as e:
        logging.error("❌ Session health check failed", exc_info=True)
        return False

def setup_chatgpt_session():
    """Setup ChatGPT session with enhanced error handling"""
    global setup_complete, last_activity
    
    try:
        if not initialize_driver():
            raise Exception("Failed to initialize driver")
            
        logging.info("🌐 Navigating to ChatGPT...")
        driver.get("https://chatgpt.com")
        
        # Wait for initial page load
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        
        logging.info("⏳ Waiting for page elements to load...")
        time.sleep(15)
        
        # Dismiss any popups
        dismiss_popups()
        
        # Verify we have the chat interface
        if not check_session_health():
            raise Exception("Chat interface not available")
            
        setup_complete = True
        last_activity = datetime.now()
        logging.info("✅ ChatGPT session setup completed")
        
        return True
        
    except Exception as e:
        logging.error("❌ Failed to setup ChatGPT session", exc_info=True)
        setup_complete = False
        raise

def send_message_to_chatgpt(message):
    """Send message to ChatGPT with enhanced reliability"""
    
    send_script = """
    const callback = arguments[arguments.length - 1];
    const message = arguments[0];
    
    (async () => {
        try {
            // Wait for page to be ready
            if (document.readyState !== 'complete') {
                await new Promise(resolve => {
                    const checkReady = () => {
                        if (document.readyState === 'complete') resolve();
                        else setTimeout(checkReady, 100);
                    };
                    checkReady();
                });
            }
            
            // Dismiss any popups first
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Find input element with multiple strategies
            const inputSelectors = [
                '[contenteditable="true"]',
                '#prompt-textarea', 
                'textarea[placeholder*="Message"]',
                '[data-testid="textbox"]',
                '.ProseMirror[contenteditable="true"]'
            ];
            
            let inputElement = null;
            for (const selector of inputSelectors) {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    if (el.offsetParent !== null && !el.disabled && !el.readOnly) {
                        inputElement = el;
                        break;
                    }
                }
                if (inputElement) break;
            }
            
            if (!inputElement) {
                callback({ success: false, error: "No input element found" });
                return;
            }
            
            // Focus and clear the input
            inputElement.focus();
            await new Promise(resolve => setTimeout(resolve, 500));
            
            // Clear existing content
            if (inputElement.tagName.toLowerCase() === 'textarea') {
                inputElement.value = '';
            } else {
                inputElement.innerHTML = '';
                inputElement.textContent = '';
            }
            
            // Type the message
            if (inputElement.tagName.toLowerCase() === 'textarea') {
                inputElement.value = message;
                inputElement.dispatchEvent(new Event('input', { bubbles: true }));
                inputElement.dispatchEvent(new Event('change', { bubbles: true }));
            } else {
                // For contenteditable elements
                inputElement.textContent = message;
                inputElement.dispatchEvent(new Event('input', { bubbles: true }));
            }
            
            // Wait for the text to be set
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Verify text was set correctly
            const currentText = inputElement.tagName.toLowerCase() === 'textarea' 
                ? inputElement.value 
                : inputElement.textContent || inputElement.innerText;
                
            if (!currentText.includes(message.substring(0, 50))) {
                callback({ success: false, error: "Failed to set message text" });
                return;
            }
            
            // Find and click send button
            const sendSelectors = [
                'button[data-testid="send-button"]',
                'button[aria-label*="Send"]',
                '[data-testid="fruitjuice-send-button"]',
                'button svg[data-testid*="send"]',
                'form button[type="submit"]',
                'button:has(svg)'
            ];
            
            let sendButton = null;
            for (const selector of sendSelectors) {
                const buttons = document.querySelectorAll(selector);
                for (const btn of buttons) {
                    if (btn.offsetParent !== null && !btn.disabled) {
                        sendButton = btn;
                        break;
                    }
                }
                if (sendButton) break;
            }
            
            if (!sendButton) {
                // Try finding by proximity to input
                const allButtons = Array.from(document.querySelectorAll('button'));
                sendButton = allButtons.find(btn => 
                    btn.offsetParent !== null && 
                    !btn.disabled &&
                    btn.getBoundingClientRect().top > inputElement.getBoundingClientRect().top - 100 &&
                    btn.getBoundingClientRect().top < inputElement.getBoundingClientRect().bottom + 100
                );
            }
            
            if (sendButton && !sendButton.disabled) {
                sendButton.click();
                callback({ success: true, message: "Message sent successfully" });
            } else {
                callback({ success: false, error: "Send button not found or disabled" });
            }
            
        } catch (error) {
            callback({ success: false, error: "JavaScript error: " + error.toString() });
        }
    })();
    """
    
    driver.set_script_timeout(30)
    result = driver.execute_async_script(send_script, message)
    
    return result

def wait_for_response():
    """Wait for ChatGPT response with improved detection"""
    
    wait_script = """
    const callback = arguments[arguments.length - 1];
    const maxWaitTime = 90000; // 90 seconds
    const checkInterval = 2000; // 2 seconds
    const startTime = Date.now();
    let lastResponse = "";
    let stableChecks = 0;
    const requiredStableChecks = 3;
    
    function extractResponse() {
        // Multiple selector strategies for assistant messages
        const selectors = [
            '[data-message-author-role="assistant"]',
            '[data-testid*="assistant"]',
            '.group.w-full.text-token-text-primary',
            '[role="presentation"] > div > div'
        ];
        
        let assistantMessages = [];
        for (const selector of selectors) {
            assistantMessages = document.querySelectorAll(selector);
            if (assistantMessages.length > 0) break;
        }
        
        if (assistantMessages.length === 0) return null;
        
        const lastMessage = assistantMessages[assistantMessages.length - 1];
        
        // Check for loading indicators
        const loadingSelectors = [
            '.result-thinking',
            '.loading',
            '.spinner',
            '[data-testid*="loading"]',
            '.animate-pulse'
        ];
        
        const isLoading = loadingSelectors.some(sel => lastMessage.querySelector(sel)) ||
                         lastMessage.textContent.includes('...') ||
                         lastMessage.textContent.includes('thinking') ||
                         lastMessage.textContent.includes('typing');
        
        if (isLoading) return null;
        
        // Extract text content
        let content = '';
        const contentElements = lastMessage.querySelectorAll('p, pre, code, li, div, span');
        
        if (contentElements.length > 0) {
            content = Array.from(contentElements)
                .map(el => el.textContent?.trim())
                .filter(text => text && text.length > 0)
                .join('\\n');
        } else {
            content = lastMessage.textContent?.trim() || '';
        }
        
        // Filter out navigation and UI elements
        const filterPatterns = [
            /^Copy code$/,
            /^Share$/,
            /^Regenerate$/,
            /^Stop generating$/,
            /^ChatGPT/
        ];
        
        const lines = content.split('\\n').filter(line => {
            const trimmed = line.trim();
            return trimmed.length > 0 && !filterPatterns.some(pattern => pattern.test(trimmed));
        });
        
        return lines.join('\\n').trim();
    }
    
    function checkForResponse() {
        const currentResponse = extractResponse();
        
        if (currentResponse && currentResponse.length > 0) {
            if (currentResponse === lastResponse) {
                stableChecks++;
                if (stableChecks >= requiredStableChecks) {
                    callback({
                        success: true,
                        response: currentResponse,
                        waitTime: Date.now() - startTime
                    });
                    return;
                }
            } else {
                stableChecks = 0;
                lastResponse = currentResponse;
            }
        }
        
        const elapsedTime = Date.now() - startTime;
        if (elapsedTime > maxWaitTime) {
            callback({
                success: false,
                response: lastResponse || null,
                error: "Timeout waiting for response",
                waitTime: elapsedTime
            });
            return;
        }
        
        setTimeout(checkForResponse, checkInterval);
    }
    
    checkForResponse();
    """
    
    driver.set_script_timeout(REQUEST_TIMEOUT)
    result = driver.execute_async_script(wait_script)
    
    return result

@app.route('/ask')
def ask():
    global setup_complete, last_activity
    
    try:
        query = request.args.get("q")
        if not query or not query.strip():
            return jsonify({"error": "No query provided"}), 400

        query = query.strip()
        logging.info(f"🔐 Processing query: {query[:100]}...")
        
        # Check session health and reinitialize if needed
        if not setup_complete or not check_session_health():
            logging.info("🔄 Reinitializing session...")
            setup_chatgpt_session()
        
        # Dismiss any popups before processing
        dismiss_popups()
        
        # Attempt to send message with retries
        send_success = False
        for attempt in range(MAX_RETRIES):
            logging.info(f"📝 Sending message (attempt {attempt + 1}/{MAX_RETRIES})")
            
            send_result = send_message_to_chatgpt(query)
            
            if send_result.get('success'):
                send_success = True
                logging.info("✅ Message sent successfully")
                break
            else:
                logging.warning(f"⚠️ Send attempt {attempt + 1} failed: {send_result.get('error')}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(3)
                    dismiss_popups()  # Try dismissing popups between attempts
        
        if not send_success:
            return jsonify({"error": "Failed to send message after retries"}), 500
        
        # Wait for response
        logging.info("⏳ Waiting for ChatGPT response...")
        time.sleep(3)  # Brief pause after sending
        
        response_result = wait_for_response()
        
        if response_result.get('success') and response_result.get('response'):
            response_text = response_result['response']
            wait_time = response_result.get('waitTime', 0)
            
            logging.info(f"✅ Response received after {wait_time}ms")
            logging.debug(f"Response length: {len(response_text)} characters")
            
            last_activity = datetime.now()
            
            return jsonify({
                "success": True,
                "bot": response_text,
                "metadata": {
                    "wait_time_ms": wait_time,
                    "response_length": len(response_text)
                }
            })
        else:
            error_msg = response_result.get('error', 'No response received')
            partial_response = response_result.get('response')
            
            logging.warning(f"⚠️ {error_msg}")
            
            # Return partial response if available
            if partial_response and len(partial_response.strip()) > 0:
                return jsonify({
                    "success": False,
                    "bot": partial_response,
                    "warning": "Partial response due to timeout",
                    "error": error_msg
                }), 206  # Partial Content
            else:
                return jsonify({"error": error_msg}), 408  # Request Timeout
    
    except Exception as e:
        logging.error("❌ Critical error in /ask endpoint", exc_info=True)
        return jsonify({
            "error": "Server error occurred",
            "details": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/restart')
def restart_browser():
    global setup_complete, driver, last_activity
    
    code = request.args.get("code")
    if code != ADMIN_CODE:
        logging.warning("🚫 Unauthorized restart attempt")
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        logging.info("♻️ Restarting browser session...")
        
        if driver:
            try:
                driver.quit()
            except:
                pass
        
        setup_complete = False
        setup_chatgpt_session()
        last_activity = datetime.now()
        
        logging.info("✅ Browser session restarted successfully")
        return jsonify({
            "success": True,
            "message": "Browser session restarted",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logging.error("❌ Failed to restart browser", exc_info=True)
        return jsonify({"error": f"Restart failed: {str(e)}"}), 500

@app.route("/api/screenshot")
def serve_screenshot():
    try:
        if not driver or not setup_complete:
            return jsonify({"error": "Browser not initialized"}), 503
            
        screenshot_png = take_screenshot_in_memory(driver)
        
        return send_file(
            BytesIO(screenshot_png),
            mimetype="image/png",
            as_attachment=False,
            download_name=f"screenshot_{int(time.time())}.png"
        )
        
    except Exception as e:
        logging.error("❌ Screenshot failed", exc_info=True)
        return jsonify({"error": f"Screenshot failed: {str(e)}"}), 500

@app.route("/status")
def status():
    """Health check endpoint"""
    global last_activity
    
    try:
        session_healthy = setup_complete and check_session_health()
        
        return jsonify({
            "status": "healthy" if session_healthy else "unhealthy",
            "setup_complete": setup_complete,
            "session_healthy": session_healthy,
            "last_activity": last_activity.isoformat() if last_activity else None,
            "uptime_seconds": time.time() - (last_activity.timestamp() if last_activity else time.time()),
            "chrome_version": get_binary_version(chrome_bin),
            "driver_version": get_binary_version(chromedriver_bin)
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route("/")
def index():
    """Main page"""
    RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000")
    return render_template("index.html", render_url=RENDER_URL)

if __name__ == '__main__':
    try:
        # Log system information
        chrome_version = get_binary_version(chrome_bin)
        chromedriver_version = get_binary_version(chromedriver_bin)
        logging.info(f"🧪 Chrome version: {chrome_version}")
        logging.info(f"🧪 ChromeDriver version: {chromedriver_version}")
        
        # Initialize ChatGPT session
        logging.info("🚀 Initializing ChatGPT session...")
        setup_chatgpt_session()
        
        # Start Flask app
        logging.info("🚀 Starting Flask app on port 10000")
        app.run(host='0.0.0.0', port=10000, debug=False)
        
    except Exception as e:
        logging.error("❌ Failed to start application", exc_info=True)
        raise
    finally:
        if driver:
            try:
                driver.quit()
                logging.info("🧹 Driver session closed")
            except:
                pass
