import os
import time
import logging
from flask import Flask

# Initialize Flask app
app = Flask(__name__)

# Configure clean logging: suppress noisy HTTP access logs, only log important events
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

@app.route('/')
def home():
    app.logger.info("Health check endpoint hit successfully.")
    return "SRE Test App is running normally."

@app.route('/crash-memory')
def crash_memory():
    """Triggers an Out-Of-Memory (OOM) crash by rapidly consuming RAM."""
    app.logger.warning("CRITICAL: Manual memory exhaustion triggered via /crash-memory.")
    bloat_list = []
    try:
        while True:
            # Rapidly allocate massive strings to exhaust 512MB RAM quickly
            bloat_list.append(' ' * 10**7)
    except Exception as e:
        app.logger.error(f"Memory exhaustion error: {str(e)}")
        raise

@app.route('/crash-exit')
def crash_exit():
    """Forces an immediate hard exit/crash."""
    app.logger.critical("Hard crash triggered via /crash-exit endpoint. Shutting down.")
    os._exit(1)

@app.route('/heavy-load')
def heavy_load():
    """Simulates CPU stress to test container load behavior."""
    app.logger.info("Starting heavy CPU load simulation.")
    start_time = time.time()
    # Spike CPU for 3 seconds
    while time.time() - start_time < 3:
        _ = [i**2 for i in range(10000)]
    app.logger.info("Heavy load simulation completed successfully.")
    return "Heavy load processed."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)