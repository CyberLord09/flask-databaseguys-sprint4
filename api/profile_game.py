"""
profile_game.py - Game Profile API

Endpoints for the CS Pathway Game profile persistence system.
Authenticated users can store/retrieve their game progress in the
_game_profile JSON column of the users table.

Routes (all require JWT auth):
  GET    /api/profile/game   - Load current user's game profile
  POST   /api/profile/game   - Create game profile (first save)
  PUT    /api/profile/game   - Update game profile (deep merge)
  DELETE /api/profile/game   - Clear game data (preserves identity)

Data model: users._game_profile (JSON)
{
  "version": "1.0",
  "localId": "local_...",
  "createdAt": "...",
  "updatedAt": "...",
  "eventId": <ever-increasing integer>,
  "identity-forge":    { "preferences": {...}, "progress": {...}, "completedAt": null },
  "wayfinding-world":  { "preferences": {...}, "progress": {...}, "completedAt": null },
  "mission-tooling":   { "progress": {...}, "completedAt": null }
}

All DB mutation logic (flag_modified, db.session.commit) lives in model/user.py.
This file is strictly a JSON pass-through layer.
"""

from flask import Blueprint, request, jsonify, g
from flask_restful import Api, Resource
from api.authorize import token_required

profile_game_api = Blueprint('profile_game_api', __name__, url_prefix='/api')
api = Api(profile_game_api)


class ProfileGameAPI:

    class _Game(Resource):

        @token_required()
        def get(self):
            """Load the current user's game profile."""
            user = g.current_user
            if user.game_profile is None:
                return {'message': 'No game profile found'}, 404
            return jsonify(user.game_profile)

        @token_required()
        def post(self):
            """Create a new game profile (first-time save)."""
            user = g.current_user
            body = request.get_json()
            if not body:
                return {'message': 'Request body is required'}, 400

            game_profile = body.get('_game_profile')
            if not game_profile:
                return {'message': '_game_profile field is required'}, 400

            if user.game_profile is not None:
                return {'message': 'Game profile already exists — use PUT to update'}, 409

            result = user.save_game_profile(game_profile)
            if result is None:
                return {'message': 'Failed to save game profile'}, 500
            return jsonify(result)

        @token_required()
        def put(self):
            """Update (deep-merge) the current user's game profile."""
            user = g.current_user
            body = request.get_json()
            if not body:
                return {'message': 'Request body is required'}, 400

            game_profile = body.get('_game_profile')
            if not game_profile:
                return {'message': '_game_profile field is required'}, 400

            try:
                result = user.update_game_profile(game_profile)
            except ValueError:
                # Incoming eventId is older than stored — return server data for reconciliation
                return jsonify({'stale': True, 'game_profile': user.game_profile}), 409

            if result is None:
                return {'message': 'Failed to update game profile'}, 500
            return jsonify(result)

        @token_required()
        def delete(self):
            """Clear game progress while preserving identity columns."""
            user = g.current_user
            if user.game_profile is None:
                return {'message': 'No game profile to clear'}, 404

            result = user.clear_game_profile()
            if result is None:
                return {'message': 'Failed to clear game profile'}, 500
            return {'message': 'Game profile cleared (identity preserved)'}, 200


# Register resource
api.add_resource(ProfileGameAPI._Game, '/profile/game')
