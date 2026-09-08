import os
import sys
from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello from Fargate Test App!"

@app.route("/crash")
def crash():
    print("CRITICAL: Hard crash triggered.", file=sys.stderr)
    # os._exit(1) immediately kills the container process with a non-zero code
    os._exit(1)

@app.route("/oom")
def oom():
    print("WARNING: Attempting to exhaust memory...", file=sys.stderr)
    huge_list = []
    while True:
        huge_list.append("X" * 10**7)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)