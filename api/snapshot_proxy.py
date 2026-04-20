"""
Snapshot Proxy API — Admin-only endpoints that forward snapshot requests
to the tracking-database-automator's internal API.
"""

import os
import requests
from flask import Blueprint, jsonify
from api.authorize import token_required

snapshot_proxy = Blueprint('snapshot_proxy', __name__, url_prefix='/api/snapshot')

AUTOMATOR_URL = os.environ.get("AUTOMATOR_URL", "http://localhost:8586")
AUTOMATOR_API_KEY = os.environ.get("AUTOMATOR_API_KEY", "")


def _proxy_snapshot(snapshot_type: str):
    """Forward a snapshot request to the automator and return its response."""
    if not AUTOMATOR_API_KEY:
        return jsonify({"success": False, "message": "AUTOMATOR_API_KEY not configured on Flask server"}), 500

    try:
        resp = requests.post(
            f"{AUTOMATOR_URL}/api/snapshot/{snapshot_type}",
            headers={"X-API-Key": AUTOMATOR_API_KEY},
            timeout=30,
        )
        return jsonify(resp.json()), resp.status_code
    except requests.ConnectionError:
        return jsonify({"success": False, "message": "Could not reach database automator service"}), 502
    except requests.Timeout:
        return jsonify({"success": False, "message": "Snapshot request timed out"}), 504
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@snapshot_proxy.route('/aurora', methods=['POST'])
@token_required("Admin")
def trigger_aurora():
    return _proxy_snapshot("aurora")


@snapshot_proxy.route('/sqlite', methods=['POST'])
@token_required("Admin")
def trigger_sqlite():
    return _proxy_snapshot("sqlite")
