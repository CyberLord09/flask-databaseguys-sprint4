from flask import Blueprint, g, request, jsonify
from flask_restful import Api, Resource
from api.authorize import auth_required, token_required
from model.persona import Persona, UserPersona
from model.user import User
from __init__ import db

persona_api = Blueprint('persona_api', __name__, url_prefix='/api')

# API docs https://flask-restful.readthedocs.io/en/latest/api.html
api = Api(persona_api)

# Category weights for matching algorithms
CATEGORY_WEIGHTS = {
    'student': 50,      # Highest priority
    'social': 25,
    'achievement': 25,
    'fantasy': 0        # Display only
}

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
            """Form optimal groups based on personas with proper weighting"""
            body = request.get_json()
            
            user_uids = body.get('user_uids', [])
            group_size = body.get('group_size', 4)
            
            if not user_uids:
                return {'message': 'user_uids required'}, 400
            
            if len(user_uids) < 2:
                return {'message': 'Need at least 2 users'}, 400
            
            if group_size < 2 or group_size > 6:
                return {'message': 'Group size must be between 2 and 6'}, 400
            
            # Query using _uid (the actual database column)
            users = User.query.filter(User._uid.in_(user_uids)).all()
            
            if len(users) != len(user_uids):
                found_uids = {u.uid for u in users}
                missing_uids = list(set(user_uids) - found_uids)
                return {
                    'message': 'Some users not found',
                    'missing_uids': missing_uids
                }, 404
            
            # Create uid->user mapping for quick lookup
            uid_to_user = {u.uid: u for u in users}
            
            # Form groups using randomized search with weighted scoring
            import random
            
            best_grouping = None
            best_avg_score = 0
            iterations = 100  # Increased iterations for better optimization
            
            for _ in range(iterations):
                shuffled = user_uids.copy()
                random.shuffle(shuffled)
                
                groups = []
                remaining = shuffled.copy()
                
                while len(remaining) >= group_size:
                    group_uids = remaining[:group_size]
                    
                    # Get users for this group
                    group_users = [uid_to_user[uid] for uid in group_uids]
                    
                    # Calculate weighted score
                    group_personas_list = []
                    for user in group_users:
                        personas = UserPersona.query.filter_by(user_id=user.id).all()
                        if personas:
                            group_personas_list.append(personas)
                    
                    score = UserPersona.calculate_weighted_team_score(group_personas_list) if group_personas_list else 0.0
                    
                    groups.append({
                        'user_uids': group_uids,
                        'team_score': score
                    })
                    
                    remaining = remaining[group_size:]
                
                # Handle leftovers (groups smaller than desired size)
                if remaining:
                    group_users = [uid_to_user[uid] for uid in remaining]
                    
                    group_personas_list = []
                    for user in group_users:
                        personas = UserPersona.query.filter_by(user_id=user.id).all()
                        if personas:
                            group_personas_list.append(personas)
                    
                    score = UserPersona.calculate_weighted_team_score(group_personas_list) if group_personas_list else 0.0
                    
                    groups.append({
                        'user_uids': remaining,
                        'team_score': score
                    })
                
                # Calculate average score for this iteration
                avg_score = sum(g['team_score'] for g in groups) / len(groups)
                
                if avg_score > best_avg_score:
                    best_avg_score = avg_score
                    best_grouping = groups
            
            return {
                'groups': best_grouping,
                'average_score': round(best_avg_score, 2)
            }, 200


    class _UserPersona(Resource):
        @token_required()
        def post(self):
            """User selects their persona (replaces existing in same category if any)"""
            body = request.get_json()
            persona_id = body.get('persona_id')
            
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
            
            # Create new assignment with category-based weight
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