from flask import Blueprint, g, request, jsonify
from flask_restful import Api, Resource
from api.authorize import auth_required, token_required
from model.skill_snapshot import SkillSnapshot
from __init__ import db

skill_passport_api = Blueprint('skill_passport_api', __name__, url_prefix='/api')
api = Api(skill_passport_api)

def _clamp(x, lo, hi):
    return max(lo, min(hi, x))

def _safe_int(v, default):
    try:
        return int(v)
    except Exception:
        return default

class SkillPassportAPI:

    class _GetPassport(Resource):
        @token_required()
        def get(self):
            """Get current user's full skill passport"""
            current_user = g.current_user
            if not current_user:
                return {'message': 'User not found'}, 404

            snapshots = (
                SkillSnapshot.query
                .filter_by(user_id=current_user.id)
                .order_by(SkillSnapshot.snapshot_date.asc())
                .all()
            )

            current_skills = snapshots[-1].read() if snapshots else None

            return {
                'user_id': current_user.id,
                'uid': current_user.uid,
                'current_skills': current_skills,
                'history': [s.read() for s in snapshots]
            }, 200

    class _CreateSnapshot(Resource):
        @token_required()
        def post(self):
            """Save a new skill snapshot"""
            current_user = g.current_user
            if not current_user:
                return {'message': 'User not found'}, 404

            body = request.get_json()
            project_name = body.get('project_name')
            if not project_name:
                return {'message': 'project_name is required'}, 400

            coding_ability = _safe_int(body.get('coding_ability'), None)
            collaboration = _safe_int(body.get('collaboration'), None)
            problem_solving = _safe_int(body.get('problem_solving'), None)
            initiative = _safe_int(body.get('initiative'), None)

            if None in [coding_ability, collaboration, problem_solving, initiative]:
                return {'message': 'coding_ability, collaboration, problem_solving, and initiative are all required'}, 400

            snapshot = SkillSnapshot(
                user_id=current_user.id,
                project_name=project_name,
                coding_ability=_clamp(coding_ability, 1, 6),
                collaboration=_clamp(collaboration, 1, 6),
                problem_solving=_clamp(problem_solving, 1, 6),
                initiative=_clamp(initiative, 1, 6)
            )

            try:
                snapshot.create()
                return snapshot.read(), 201
            except Exception as e:
                db.session.rollback()
                return {'message': f'Error saving snapshot: {str(e)}'}, 500

    class _AdminGetPassport(Resource):
        @auth_required(roles="Admin")
        def get(self, user_id):
            """Admin: get any student's full skill passport"""
            snapshots = (
                SkillSnapshot.query
                .filter_by(user_id=user_id)
                .order_by(SkillSnapshot.snapshot_date.asc())
                .all()
            )

            current_skills = snapshots[-1].read() if snapshots else None

            return {
                'user_id': user_id,
                'current_skills': current_skills,
                'history': [s.read() for s in snapshots]
            }, 200

    api.add_resource(_GetPassport, '/user/skill-passport')
    api.add_resource(_CreateSnapshot, '/user/skill-snapshot')
    api.add_resource(_AdminGetPassport, '/admin/skill-passport/<int:user_id>')