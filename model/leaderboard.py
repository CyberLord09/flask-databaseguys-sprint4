"""
Leaderboard event models.

Separate tables for SCORE_COUNTER (dynamic) and ELEMENTARY_LEADERBOARD (elementary)
so the frontend can read/write both modes through /api/events/* endpoints.
"""
from datetime import datetime
from sqlite3 import IntegrityError

from __init__ import db


class ScoreCounterEvent(db.Model):
	"""Dynamic leaderboard score event."""

	__tablename__ = 'leaderboard'

	id = db.Column(db.Integer, primary_key=True)
	_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
	_payload = db.Column(db.JSON, nullable=False)
	_timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

	user = db.relationship('User', foreign_keys=[_user_id], backref=db.backref('score_counter_events', lazy=True))

	def __init__(self, payload, user_id=None):
		self._payload = payload if isinstance(payload, dict) else {}
		self._user_id = user_id
		self._timestamp = datetime.utcnow()

	def create(self):
		"""Persist the event and return self on success."""
		try:
			db.session.add(self)
			db.session.commit()
			return self
		except IntegrityError:
			db.session.rollback()
			return None
		except Exception:
			db.session.rollback()
			raise

	def read(self):
		"""Return event data in a Java-like shape expected by the frontend."""
		return {
			'id': self.id,
			'userId': self._user_id,
			'user': {
				'id': self.user.id,
				'uid': self.user.uid,
				'name': self.user.name,
			} if self.user else None,
			'algoName': 'SCORE_COUNTER',
			'eventName': 'SCORE_COUNTER',
			'payload': self._payload or {},
			'timestamp': self._timestamp.isoformat() if self._timestamp else None,
		}

	def delete(self):
		"""Delete this event row."""
		try:
			db.session.delete(self)
			db.session.commit()
			return True
		except Exception:
			db.session.rollback()
			return False

	@staticmethod
	def get_by_id(event_id):
		return ScoreCounterEvent.query.get(event_id)

	@staticmethod
	def get_all(game_name=None, limit=200):
		query = ScoreCounterEvent.query.order_by(ScoreCounterEvent._timestamp.desc()).limit(limit)
		events = query.all()

		if game_name:
			filtered = []
			for event in events:
				payload = event._payload or {}
				if payload.get('gameName') == game_name:
					filtered.append(event)
			return filtered

		return events


class ElementaryLeaderboardEvent(db.Model):
	"""Elementary leaderboard event (user-managed scores)."""

	__tablename__ = 'elementary_leaderboard_events'

	id = db.Column(db.Integer, primary_key=True)
	_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
	_payload = db.Column(db.JSON, nullable=False)
	_timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

	user = db.relationship('User', foreign_keys=[_user_id], backref=db.backref('elementary_leaderboard_events', lazy=True))

	def __init__(self, payload, user_id=None):
		self._payload = payload if isinstance(payload, dict) else {}
		self._user_id = user_id
		self._timestamp = datetime.utcnow()

	def create(self):
		"""Persist the event and return self on success."""
		try:
			db.session.add(self)
			db.session.commit()
			return self
		except IntegrityError:
			db.session.rollback()
			return None
		except Exception:
			db.session.rollback()
			raise

	def read(self):
		"""Return event data in a Java-like shape expected by the frontend."""
		return {
			'id': self.id,
			'userId': self._user_id,
			'user': {
				'id': self.user.id,
				'uid': self.user.uid,
				'name': self.user.name,
			} if self.user else None,
			'algoName': 'ELEMENTARY_LEADERBOARD',
			'eventName': 'ELEMENTARY_LEADERBOARD',
			'payload': self._payload or {},
			'timestamp': self._timestamp.isoformat() if self._timestamp else None,
		}

	def delete(self):
		"""Delete this event row."""
		try:
			db.session.delete(self)
			db.session.commit()
			return True
		except Exception:
			db.session.rollback()
			return False

	@staticmethod
	def get_by_id(event_id):
		return ElementaryLeaderboardEvent.query.get(event_id)

	@staticmethod
	def get_all(game_name=None, limit=200):
		query = ElementaryLeaderboardEvent.query.order_by(ElementaryLeaderboardEvent._timestamp.desc()).limit(limit)
		events = query.all()

		if game_name:
			filtered = []
			for event in events:
				payload = event._payload or {}
				if payload.get('gameName') == game_name:
					filtered.append(event)
			return filtered

		return events

