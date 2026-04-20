import random

from flask import Blueprint, g, request, jsonify
from flask_restful import Api, Resource
from api.authorize import auth_required, token_required
from model.persona import Persona, UserPersona
from model.user import User
from __init__ import db

persona_api = Blueprint('persona_api', __name__, url_prefix='/api')

# API docs https://flask-restful.readthedocs.io/en/latest/api.html
api = Api(persona_api)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _safe_int(v, default):
    try:
        return int(v)
    except Exception:
        return default


def _normalize_feedback_rows(rows):
    """
    Accepts list of dicts. Returns only rows with:
      - personas: list[str]
      - student_rating_1to5: int 1..5
      - teacher_rating_1to5: int 1..5
    """
    if not isinstance(rows, list):
        return []

    cleaned = []
    for r in rows:
        if not isinstance(r, dict):
            continue

        personas = r.get("personas")
        if not isinstance(personas, list) or len(personas) < 2:
            continue

        # Allow either alias list or objects; normalize to alias strings
        persona_aliases = []
        for p in personas:
            if isinstance(p, str):
                persona_aliases.append(p.strip())
            elif isinstance(p, dict) and "alias" in p:
                persona_aliases.append(str(p["alias"]).strip())

        persona_aliases = [a for a in persona_aliases if a]
        if len(persona_aliases) < 2:
            continue

        s = _safe_int(r.get("student_rating_1to5"), 3)
        t = _safe_int(r.get("teacher_rating_1to5"), 3)

        if not (1 <= s <= 5 and 1 <= t <= 5):
            continue

        cleaned.append({
            "personas": persona_aliases,
            "student_rating_1to5": s,
            "teacher_rating_1to5": t,
        })

    return cleaned


def _feedback_to_pair_delta(feedback_rows, alpha=2.0):
    """
    Learn persona-pair adjustments:
      avg rating 5 => + (2 * alpha)
      avg rating 1 => - (2 * alpha)

    Returns dict[(p1,p2)] = delta
    """
    from collections import defaultdict

    pair_delta = defaultdict(float)
    rows = _normalize_feedback_rows(feedback_rows)

    for r in rows:
        personas = r["personas"]
        avg = (
            float(r["student_rating_1to5"]) + float(r["teacher_rating_1to5"])
        ) / 2.0  # 1..5
        centered = avg - 3.0  # -2..+2
        delta = centered * alpha

        # apply delta to all unordered pairs
        for i in range(len(personas)):
            for j in range(i + 1, len(personas)):
                p1, p2 = sorted([personas[i], personas[j]])
                pair_delta[(p1, p2)] += delta

    return dict(pair_delta)


def _extract_primary_student_alias(user_id):
    """
    Pick the most "important" student persona for a user:
      - highest weight wins
      - if tie, latest selected_at wins
    Returns alias or None.
    """
    ups = (
        UserPersona.query
        .join(Persona, UserPersona.persona_id == Persona.id)
        .filter(UserPersona.user_id == user_id, Persona._category == "student")
        .all()
    )

    if not ups:
        return None

    ups_sorted = sorted(
        ups,
        key=lambda up: (up.weight or 0, up.selected_at or 0),
        reverse=True
    )
    return ups_sorted[0].persona._alias


def _team_feedback_adjustment(student_aliases, pair_delta, max_bonus=15.0):
    """
    Sum learned deltas across all pairs within team.
    """
    if not student_aliases or len(student_aliases) < 2 or not pair_delta:
        return 0.0

    total = 0.0
    for i in range(len(student_aliases)):
        for j in range(i + 1, len(student_aliases)):
            p1, p2 = sorted([student_aliases[i], student_aliases[j]])
            total += float(pair_delta.get((p1, p2), 0.0))

    return _clamp(total, -max_bonus, max_bonus)


def _build_group_personas_list(group_users):
    """
    Build the persona list structure required by UserPersona.calculate_team_score().
    """
    group_personas_list = []

    for user in group_users:
        personas = UserPersona.query.filter_by(user_id=user.id).all()
        if personas:
            group_personas_list.append(personas)

    return group_personas_list


def _calculate_base_team_score(group_users):
    """
    Calculate the original compatibility score with no learned feedback.
    """
    group_personas_list = _build_group_personas_list(group_users)
    if not group_personas_list:
        return 0.0

    return UserPersona.calculate_team_score(group_personas_list)


def _calculate_team_score_with_feedback(group_users, pair_delta):
    """
    base_score = existing UserPersona.calculate_team_score(...)
    adjusted_score = base_score + feedback_adjustment(student persona pairs)
    """
    base = _calculate_base_team_score(group_users)

    student_aliases = []
    for user in group_users:
        alias = _extract_primary_student_alias(user.id)
        if alias:
            student_aliases.append(alias)

    fb = _team_feedback_adjustment(student_aliases, pair_delta, max_bonus=15.0)
    return round(_clamp(base + fb, 0.0, 100.0), 2)


def _calculate_group_score(group_users, pair_delta=None):
    """
    Calculate the final score for one group.
    """
    if not group_users:
        return 0.0

    if pair_delta:
        return _calculate_team_score_with_feedback(group_users, pair_delta)

    return round(_calculate_base_team_score(group_users), 2)


GROUP_FORMATION_ERRORS = {
    "MISSING_USER_UIDS": "user_uids required",
    "NOT_ENOUGH_USERS": "Need at least 2 users",
    "INVALID_GROUP_SIZE": "group_size must be between 2 and 10",
    "USERS_NOT_FOUND": "Some users not found"
}


def _parse_group_request(body):
    """
    Parse and validate request body for group formation.
    """
    body = body or {}

    user_uids = body.get("user_uids", [])
    group_size = _safe_int(body.get("group_size", 4), 4)
    incorporate = bool(body.get("incorporate_prior_experiences", False))
    feedback_rows = body.get("feedback_rows", [])

    if not user_uids:
        raise ValueError("MISSING_USER_UIDS")

    if len(user_uids) < 2:
        raise ValueError("NOT_ENOUGH_USERS")

    if group_size < 2 or group_size > 10:
        raise ValueError("INVALID_GROUP_SIZE")

    return {
        "user_uids": user_uids,
        "group_size": group_size,
        "incorporate": incorporate,
        "feedback_rows": feedback_rows
    }


def _fetch_users_by_uids(user_uids):
    """
    Fetch all users requested by UID and detect missing ones.
    """
    users = User.query.filter(User._uid.in_(user_uids)).all()

    if len(users) != len(user_uids):
        found_uids = {u.uid for u in users}
        missing_uids = list(set(user_uids) - found_uids)
        raise LookupError({
            "code": "USERS_NOT_FOUND",
            "missing_uids": missing_uids
        })

    return users


def _build_uid_lookup(users):
    """
    Build uid -> user lookup table.
    """
    return {u.uid: u for u in users}


def _learn_pair_delta_if_enabled(incorporate, feedback_rows):
    """
    Learn persona-pair adjustments only when enabled.
    Fails softly if feedback is malformed.
    """
    if not incorporate:
        return {}

    try:
        return _feedback_to_pair_delta(feedback_rows, alpha=2.0)
    except Exception:
        return {}


def _build_groups_from_uids(shuffled_uids, group_size, uid_to_user, pair_delta=None):
    """
    Split shuffled users into groups and score each group.
    """
    groups = []
    remaining = shuffled_uids.copy()

    while len(remaining) >= group_size:
        group_uids = remaining[:group_size]
        group_users = [uid_to_user[uid] for uid in group_uids]
        score = _calculate_group_score(group_users, pair_delta)

        groups.append({
            "user_uids": group_uids,
            "team_score": score
        })

        remaining = remaining[group_size:]

    if remaining:
        leftover_users = [uid_to_user[uid] for uid in remaining]
        score = _calculate_group_score(leftover_users, pair_delta)

        groups.append({
            "user_uids": remaining,
            "team_score": score
        })

    return groups


def _calculate_average_group_score(groups):
    """
    Calculate average score across all formed groups.
    """
    if not groups:
        return 0.0

    return sum(g["team_score"] for g in groups) / len(groups)


def _find_best_grouping(user_uids, group_size, uid_to_user, pair_delta=None):
    """
    Try multiple random groupings and keep the best one.
    """
    best_grouping = None
    best_avg_score = -1.0

    iterations = 80 if pair_delta else 50

    for _ in range(iterations):
        shuffled = user_uids.copy()
        random.shuffle(shuffled)

        groups = _build_groups_from_uids(
            shuffled_uids=shuffled,
            group_size=group_size,
            uid_to_user=uid_to_user,
            pair_delta=pair_delta
        )

        avg_score = _calculate_average_group_score(groups)

        if avg_score > best_avg_score:
            best_avg_score = avg_score
            best_grouping = groups

    return best_grouping, round(best_avg_score, 2)


def _build_form_groups_response(best_grouping, best_avg_score, incorporate, pair_delta):
    """
    Build final API response payload.
    """
    return {
        "groups": best_grouping,
        "average_score": best_avg_score,
        "method": "ai_feedback" if incorporate and pair_delta else "ai",
        "feedback_used": bool(pair_delta),
        "learned_pairs": len(pair_delta)
    }


def _orchestrate_group_formation(body):
    """
    Coordinate the complete group formation workflow.
    """
    parsed = _parse_group_request(body)
    users = _fetch_users_by_uids(parsed["user_uids"])
    uid_to_user = _build_uid_lookup(users)
    pair_delta = _learn_pair_delta_if_enabled(
        parsed["incorporate"],
        parsed["feedback_rows"]
    )

    best_grouping, best_avg_score = _find_best_grouping(
        user_uids=parsed["user_uids"],
        group_size=parsed["group_size"],
        uid_to_user=uid_to_user,
        pair_delta=pair_delta
    )

    return _build_form_groups_response(
        best_grouping=best_grouping,
        best_avg_score=best_avg_score,
        incorporate=parsed["incorporate"],
        pair_delta=pair_delta
    )


class PersonaAPI:

    class _Create(Resource):
        @auth_required(roles="Admin")
        def post(self):
            """Create a new persona"""
            body = request.get_json()

            # Validate required fields
            alias = body.get('alias')
            if alias is None or len(alias) < 2:
                return {'message': 'Alias is missing or is less than 2 characters'}, 400

            category = body.get('category')
            if category is None:
                return {'message': 'Category is required'}, 400

            bio_map = body.get('bio_map')
            if bio_map is None:
                return {'message': 'Bio map is required'}, 400

            # Validate bio_map has required fields
            if not bio_map.get('title'):
                return {'message': 'Bio map must include title'}, 400
            if not bio_map.get('description'):
                return {'message': 'Bio map must include description'}, 400

            empathy_map = body.get('empathy_map')

            # Create persona object
            persona_obj = Persona(
                _alias=alias,
                _category=category,
                _bio_map=bio_map,
                _empathy_map=empathy_map
            )

            # Add to database
            persona = persona_obj.create()
            if persona:
                return jsonify(persona.read())

            return {'message': f'Failed to create persona {alias}, possibly duplicate alias'}, 400

    class _Read(Resource):
        def get(self, id=None):
            """Get persona by ID or all personas"""
            if id is not None:
                # Get single persona by ID
                persona = Persona.query.get(id)
                if persona is None:
                    return {'message': f'Persona with id {id} not found'}, 404
                return jsonify(persona.read())
            else:
                # Get all personas
                personas = Persona.query.all()
                json_ready = [persona.read() for persona in personas]
                return jsonify(json_ready)

    class _Update(Resource):
        @auth_required(roles="Admin")
        def put(self, id):
            """Update an existing persona"""
            body = request.get_json()

            # Find the persona
            persona = Persona.query.get(id)
            if persona is None:
                return {'message': f'Persona with id {id} not found'}, 404

            # Update fields if provided
            if 'alias' in body:
                alias = body.get('alias')
                if alias and len(alias) >= 2:
                    persona._alias = alias
                else:
                    return {'message': 'Alias must be at least 2 characters'}, 400

            if 'category' in body:
                category = body.get('category')
                if category:
                    persona._category = category

            if 'bio_map' in body:
                bio_map = body.get('bio_map')
                if bio_map:
                    persona._bio_map = bio_map

            if 'empathy_map' in body:
                empathy_map = body.get('empathy_map')
                persona._empathy_map = empathy_map

            # Commit changes
            try:
                db.session.commit()
                return jsonify(persona.read())
            except Exception as e:
                db.session.rollback()
                return {'message': f'Error updating persona: {str(e)}'}, 500

    class _Delete(Resource):
        @auth_required(roles="Admin")
        def delete(self, id):
            """Delete a persona"""
            persona = Persona.query.get(id)
            if persona is None:
                return {'message': f'Persona with id {id} not found'}, 404

            json_data = persona.read()

            try:
                db.session.delete(persona)
                db.session.commit()
                return {'message': f'Deleted persona: {json_data["alias"]}', 'persona': json_data}, 200
            except Exception as e:
                db.session.rollback()
                return {'message': f'Error deleting persona: {str(e)}'}, 500

    class _EvaluateGroup(Resource):
        def post(self):
            """Evaluate persona compatibility for a group"""
            body = request.get_json()

            user_uids = body.get('user_uids', [])
            if not user_uids:
                return {'message': 'user_uids required'}, 400

            # Query using _uid (the actual database column, not the property)
            users = User.query.filter(User._uid.in_(user_uids)).all()

            # Check for missing users
            if len(users) != len(user_uids):
                found_uids = {u.uid for u in users}  # Use .uid property for display
                missing_uids = list(set(user_uids) - found_uids)
                return {
                    'message': 'Some users not found',
                    'missing_uids': missing_uids
                }, 404

            # Collect personas for each user
            user_personas_list = []
            members_detail = []

            for user in users:
                personas = UserPersona.query.filter_by(user_id=user.id).all()

                if personas:
                    user_personas_list.append(personas)

                members_detail.append({
                    'uid': user.uid,  # Use property for display
                    'name': user.name,
                    'personas': [
                        {
                            'title': up.persona.title,
                            'category': up.persona.category,
                            'weight': up.weight
                        }
                        for up in personas
                    ]
                })

            # Handle case where no personas found
            if not user_personas_list:
                return {
                    'team_score': 0.0,
                    'members': members_detail,
                    'evaluation': 'No personas found',
                    'message': 'Users have no persona assignments'
                }, 200

            # Calculate team score
            team_score = UserPersona.calculate_team_score(user_personas_list)

            # Provide evaluation
            if team_score >= 80:
                evaluation = 'Excellent - Highly balanced'
            elif team_score >= 70:
                evaluation = 'Good - Well-balanced'
            elif team_score >= 60:
                evaluation = 'Fair - Moderately balanced'
            else:
                evaluation = 'Needs improvement'

            return {
                'team_score': team_score,
                'members': members_detail,
                'evaluation': evaluation
            }, 200

    class _FormGroups(Resource):
        def post(self):
            """Form optimal groups based on personas, optionally incorporating prior experiences."""
            try:
                body = request.get_json() or {}
                result = _orchestrate_group_formation(body)
                return result, 200

            except ValueError as e:
                error_code = str(e)
                return {
                    "message": GROUP_FORMATION_ERRORS.get(error_code, "Invalid request")
                }, 400

            except LookupError as e:
                error_data = e.args[0] if e.args else {}
                return {
                    "message": GROUP_FORMATION_ERRORS["USERS_NOT_FOUND"],
                    "missing_uids": error_data.get("missing_uids", [])
                }, 404

            except Exception as e:
                return {
                    "message": f"Error forming groups: {str(e)}"
                }, 500

    class _UserPersona(Resource):
        @token_required()
        def post(self):
            """User selects their persona (replaces existing in same category if any)"""
            body = request.get_json()
            persona_id = body.get('persona_id')
            weight = body.get('weight', 1)

            if not persona_id:
                return {'message': 'persona_id is required'}, 400

            # Get current user FROM g.current_user
            current_user = g.current_user
            if not current_user:
                return {'message': 'User not found'}, 404

            # Verify persona exists
            persona = Persona.query.get(persona_id)
            if not persona:
                return {'message': 'Persona not found'}, 404

            # Get the category of the selected persona
            category = persona.category

            # Check if user already has THIS exact persona
            existing = UserPersona.query.filter_by(
                user_id=current_user.id,
                persona_id=persona_id
            ).first()

            if existing:
                return {'message': 'Persona already selected'}, 200  # Changed to 200, it's OK

            # Delete any existing persona in the SAME CATEGORY (not all personas)
            # First get all user's personas
            user_personas = UserPersona.query.filter_by(user_id=current_user.id).all()

            # Find and delete any in the same category
            for up in user_personas:
                if up.persona.category == category:
                    db.session.delete(up)

            # Create new assignment
            user_persona = UserPersona(
                user=current_user,
                persona=persona,
                weight=weight
            )

            try:
                db.session.add(user_persona)
                db.session.commit()
                return {'message': 'Persona selected', 'persona_id': persona_id, 'category': category}, 201
            except Exception as e:
                db.session.rollback()
                return {'message': f'Error: {str(e)}'}, 500

    class _GetUserPersonas(Resource):
        @token_required()
        def get(self):
            """Get current user's personas grouped by category"""
            current_user = g.current_user
            if not current_user:
                return {'message': 'User not found'}, 404

            user_personas = UserPersona.query.filter_by(user_id=current_user.id).all()

            # Group personas by category
            personas_by_category = {}
            for up in user_personas:
                category = up.persona.category
                personas_by_category[category] = {
                    'persona_id': up.persona_id,
                    'alias': up.persona.alias,
                    'weight': up.weight,
                    'selected_at': up.selected_at.isoformat() if up.selected_at else None
                }

            return {
                'personas': personas_by_category,
                'total_selected': len(personas_by_category)
            }, 200

    class _DeleteUserPersona(Resource):
        @token_required()
        def delete(self, persona_id):
            """User removes their persona"""
            current_user = g.current_user
            if not current_user:
                return {'message': 'User not found'}, 404

            # Find assignment
            user_persona = UserPersona.query.filter_by(
                user_id=current_user.id,
                persona_id=persona_id
            ).first()

            if not user_persona:
                return {'message': 'Persona not assigned'}, 404

            category = user_persona.persona.category

            try:
                db.session.delete(user_persona)
                db.session.commit()
                return {'message': 'Persona removed', 'category': category}, 200
            except Exception as e:
                db.session.rollback()
                return {'message': f'Error: {str(e)}'}, 500

    api.add_resource(_UserPersona, '/user/persona')
    api.add_resource(_GetUserPersonas, '/user/personas')
    api.add_resource(_DeleteUserPersona, '/user/persona/<int:persona_id>')

    # Building RESTful API endpoints
    api.add_resource(_Create, '/persona/create')
    api.add_resource(_Read, '/persona', '/persona/<int:id>')
    api.add_resource(_Update, '/persona/update/<int:id>')
    api.add_resource(_Delete, '/persona/delete/<int:id>')
    api.add_resource(_EvaluateGroup, '/persona/evaluate-group')
    api.add_resource(_FormGroups, '/persona/form-groups')