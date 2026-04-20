import eventlet
eventlet.monkey_patch()

from flask import Flask, jsonify, request
from flask_socketio import SocketIO

import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

@app.get("/health")
def health():
    # Get current server time
    server_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    # Try to get client IP
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    # Latency: if client sends ?ping=timestamp, return round-trip
    ping = request.args.get("ping")
    latency = None
    if ping:
        try:
            latency = time.time() - float(ping)
        except Exception:
            latency = None
    resp = {
        "ok": True,
        "service": "websocket",
        "server_time_utc": server_time,
        "client_ip": client_ip,
        "latency_seconds": latency,
        "info": "Send ?ping=<epoch_seconds> to measure latency."
    }
    return jsonify(resp), 200


@app.get("/")
def index():
    return jsonify({"message": "websocket service running"}), 200


@socketio.on('connect')
def handle_connect():
    print(f"[SERVER] Client connected: {request.sid}")
    socketio.emit('live_update', {'msg': 'Welcome! Live data will stream here.'}, room=request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    print(f"[SERVER] Client disconnected: {request.sid}")

@socketio.on('get_live_info')
def handle_live_info(data=None):
    response = {"info": "This is live info from the server!"}
    socketio.emit('live_update', response, room=request.sid)

if __name__ == "__main__":
    # Keep this aligned with `websocket/docker-compose.yml`
    socketio.run(app, host="0.0.0.0", port=8590)