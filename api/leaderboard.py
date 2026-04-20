"""
Leaderboard API.

Provides endpoints for dynamic and elementary leaderboards:
- GET/POST /api/dynamic/leaderboard (SCORE_COUNTER)
- GET/POST /api/events/ELEMENTARY_LEADERBOARD
- DELETE /api/events/ELEMENTARY_LEADERBOARD/<id>
"""
from flask import Blueprint, g, jsonify, request
from flask_restful import Api, Resource
from flask_login import current_user

from api.authorize import token_required
from model.leaderboard import ScoreCounterEvent, ElementaryLeaderboardEvent


# Dynamic leaderboard blueprint
dynamic_api = Blueprint('dynamic_api', __name__, url_prefix='/api/dynamic')
dynamic_restful = Api(dynamic_api)

# Elementary leaderboard blueprint
events_api = Blueprint('events_api', __name__, url_prefix='/api/events')
events_restful = Api(events_api)


def _normalize_payload(body):
	payload = (body or {}).get('payload')
	if payload is None:
		payload = {}
	if not isinstance(payload, dict):
		return None
	return payload


class ScoreCounterAPI(Resource):
	def get(self):
		game_name = request.args.get('gameName')
		limit = request.args.get('limit', 200, type=int)

		events = ScoreCounterEvent.get_all(game_name=game_name, limit=limit)
		return jsonify([event.read() for event in events])

	@token_required()
	def post(self):
		body = request.get_json() or {}
		payload = _normalize_payload(body)
		if payload is None:
			return {'message': 'payload must be an object'}, 400

		if payload.get('score') is None:
			return {'message': 'payload.score is required'}, 400

		user_id = getattr(g, 'current_user', None).id if getattr(g, 'current_user', None) else None
		event = ScoreCounterEvent(payload=payload, user_id=user_id)
		created = event.create()
		if not created:
			return {'message': 'Failed to create score event'}, 500

		return jsonify(created.read())


class ElementaryLeaderboardAPI(Resource):
	def get(self):
		game_name = request.args.get('gameName')
		limit = request.args.get('limit', 200, type=int)

		events = ElementaryLeaderboardEvent.get_all(game_name=game_name, limit=limit)
		return jsonify([event.read() for event in events])

	@token_required()
	def post(self):
		body = request.get_json() or {}
		payload = _normalize_payload(body)
		if payload is None:
			return {'message': 'payload must be an object'}, 400

		if not payload.get('user'):
			return {'message': 'payload.user is required'}, 400
		if payload.get('score') is None:
			return {'message': 'payload.score is required'}, 400

		user_id = getattr(g, 'current_user', None).id if getattr(g, 'current_user', None) else None
		event = ElementaryLeaderboardEvent(payload=payload, user_id=user_id)
		created = event.create()
		if not created:
			return {'message': 'Failed to create elementary leaderboard event'}, 500

		return jsonify(created.read())


class ElementaryLeaderboardItemAPI(Resource):
	@token_required()
	def delete(self, event_id):
		event = ElementaryLeaderboardEvent.get_by_id(event_id)
		if not event:
			return {'message': 'Event not found'}, 404

		if not event.delete():
			return {'message': 'Failed to delete event'}, 500

		return {'message': 'Deleted successfully'}, 200


dynamic_restful.add_resource(ScoreCounterAPI, '/leaderboard')
events_restful.add_resource(ElementaryLeaderboardAPI, '/ELEMENTARY_LEADERBOARD')
events_restful.add_resource(ElementaryLeaderboardItemAPI, '/ELEMENTARY_LEADERBOARD/<int:event_id>')

