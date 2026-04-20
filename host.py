"""
Run this file with `python host.py` to start this server to show information to Mr. Mortensen!

Make sure to first initialize `venv` and install necessary dependencies by running `./scripts/venv.sh`.

This file retrieves the following information:
- Operating system
- XCode developer tools installed (MacOS only)
- Checks if the following are installed, and their versions
  - XCode developer tools (MacOS only)
  - Homebrew (MacOS only)
  - Git
  - Python
  - Pip
  - Ruby
  - Bundler
  - RubyGems
  - Jupyter
- Stored GitHub username/email
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_restful import Api, Resource
import subprocess
import platform
import shutil
import os
import re

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=[
    "https://pages.opencodingsociety.com",
    "http://localhost:4100",
    "http://127.0.0.1:4100",
    "http://localhost:4500",      # ← Jekyll default port
    "http://127.0.0.1:4500",
    "http://localhost:4200",      # ← common fallback
    "http://127.0.0.1:4200",
    "null",                       # ← for when the .ipynb is opened directly as a file
])

api = Api(app)

# --- API Resource ---
class HostAPI(Resource):
    def get(self):
        """Return a structured JSON object with parsed versions and raw outputs.

        For most developer tools we parse version number and also return the raw output. For a few commands (like Jupyter and git config values) we keep the full string as the primary value.
        """
        def run_cmd(cmd, timeout=10):
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout,
                )
                stdout = proc.stdout.strip()
                stderr = proc.stderr.strip()
                combined = "\n".join([s for s in (stdout, stderr) if s])
                return {
                    "cmd": cmd,
                    "returncode": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "combined": combined,
                }
            except subprocess.TimeoutExpired:
                return {"cmd": cmd, "error": "timeout", "returncode": None}
            except Exception as e:
                return {"cmd": cmd, "error": str(e), "returncode": None}

        def parse_version(text):
            if not text:
                return None
            # Find first semver-like token (e.g. 3, 3.1, 3.1.4)
            m = re.search(r"(\d+(?:\.\d+){0,3})", text)
            return m.group(1) if m else None

        # Info about the person's system, also some other random stuff
        host_data = {
            "OS": platform.system(),
            "OS Release": platform.release(),
            "OS Version": platform.version(),
            "Architecture": platform.machine(),
            "Python Executable Path": os.path.abspath(shutil.which('python') or ''),
            "checks": {},
        }

        # third param is a mode, basically if raw means return full string and version gets the first one
        check_cmds = [
            ("python", "python --version", "version"),
            ("pip", "pip --version", "version"),
            ("ruby", "ruby -v", "version"),
            ("bundler", "bundle -v", "version"),
            ("gem", "gem -v", "version"),
            ("jupyter", "jupyter --version", "raw"),
            ("jupyter_kernelspecs", "jupyter kernelspec list", "raw"),
            ("git", "git --version", "version"),
            ("git_user_name", "git config --global user.name", "raw"),
            ("git_user_email", "git config --global user.email", "raw"),
            ("brew", "which brew && brew --version", "version"),
            ("xcode_select", "xcode-select -p", "raw"),
            ("uname", "uname -a", "raw"),
        ]

        for name, cmd, mode in check_cmds:
            # Skip macos-only checks if not on a mac
            if (name == "brew" or name == "xcode_select") and host_data["OS"] != "Darwin":
                continue
            
            res = run_cmd(cmd)
            installed = res.get("returncode") == 0 and bool(res.get("combined"))
            raw = res.get("combined") or ""
            if mode == "raw":
                host_data[name] = {
                    "installed": installed,
                    "value": raw,
                }
            else:
                version = parse_version(raw)
                host_data[name] = {
                    "installed": installed,
                    "version": version,
                    "raw": raw,
                }

        return jsonify(host_data)

api.add_resource(HostAPI, '/api/host')

# Wee can use @app.route for HTML endpoints, this will be style for Admin UI
@app.route('/')
def say_hello():
    html_content = """
    <html>
    <head>
        <title>Hello</title>
    </head>
    <body>
        <h2>Hello, World!</h2>
    </body>
    </html>
    """
    return html_content

if __name__ == '__main__':
    app.run(port=6741, debug=True)