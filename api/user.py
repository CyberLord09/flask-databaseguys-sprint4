import jwt
from flask import Blueprint, app, request, jsonify, current_app, Response, g
from flask_restful import Api, Resource # used for REST API building
from datetime import datetime
from __init__ import app, db
from api.authorize import token_required
from model.user import User
from model.github import GitHubUser
import os

user_api = Blueprint('user_api', __name__,
                   url_prefix='/api')

# API docs https://flask-restful.readthedocs.io/en/latest/api.html
api = Api(user_api)

class UserAPI:        
    class _ID(Resource):  # Individual identification API operation
        @token_required()
        def get(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            ''' Return the current user as a json object with role information '''
            user_data = current_user.read()
            # Add role information to response
            user_data['role'] = current_user.role
            user_data['is_admin'] = current_user.is_admin()
            user_data['is_teacher'] = current_user.is_teacher()
            return jsonify(user_data)
    
    class _BULK(Resource):  # Users API operation for Create, Read, Update, Delete 
        def post(self):
            ''' Handle bulk user creation by sending POST requests to the single user endpoint '''
            users = request.get_json()
            
            if not isinstance(users, list):
                return {'message': 'Expected a list of user data'}, 400
            
            results = {'errors': []}
            
            with current_app.test_client() as client:
                for user in users:
                    # Set a default password as we don't have it for bulk creation
                    user["password"] = app.config['DEFAULT_PASSWORD']
                    
                    # Simulate a POST request to the single user creation endpoint
                    response = client.post('/api/user', json=user)
                    
                    if response.status_code != 200:  # Assuming success status code is 200
                        results['errors'].append(response.get_json())
                        continue
                
                    uid = user.get('uid')
                    user_obj = User.query.filter_by(_uid=uid).first()
                    # Process sections if provided
                    if user_obj is not None:
                        print("Creating:", user_obj.uid)
                        abbreviations = [section["abbreviation"] for section in user.get('sections', [])]
                        if len(abbreviations) > 0:  # Check if the list is not empty
                            section_obj = user_obj.add_sections(abbreviations)
                            if section_obj:
                                # update the year of the added sections
                                for section in user.get('sections'):
                                    user_obj.update_section(section)
                            else:
                                results['errors'].append({'message': f'Failed to add sections {abbreviations} to user {uid}'})
                                
            
            return jsonify(results) 
            
    class _CRUD(Resource):  # Users API operation for Create, Read, Update, Delete 
        def post(self): # Create method
            """
            Create a new user.

            Reads data from the JSON body of the request, validates the input, and creates a new user in the database.

            Returns:
                JSON response with the created user details or an error message.
            """
            
            # Read data for json body
            body = request.get_json()
            
            # Debug logging
            #print(f"Received signup request with body: {body}")
            
            ''' Avoid garbage in, error checking '''
            # validate name
            name = body.get('name')
            if name is None or len(name) < 2:
                return {'message': f'Name is missing, or is less than 2 characters'}, 400
            
            # validate uid
            uid = body.get('uid')
            if uid is None or len(uid) < 2:
                return {'message': f'User ID is missing, or is less than 2 characters'}, 400
          
            # check if uid is a GitHub account
            _, status = GitHubUser().get(uid)
            if status != 200:
                return {'message': f'User ID {uid} not a valid GitHub account' }, 404
            
            ''' User object creation '''
            #1: Setup minimal User object using __init__ method
            password = body.get('password')
            if password is not None:
                if len(password) < 8 and not password.startswith("pbkdf2:sha256:"):
                    return {'message': 'Password must be at least 8 characters'}, 400
                user_obj = User(name=name, uid=uid, password=password)
            else:
                user_obj = User(name=name, uid=uid)
            
            # Handle additional fields that frontend sends
            # Create a cleaned body with only the fields User model expects
            cleaned_body = {
                'name': name,
                'uid': uid,
                'password': password,
                'email': body.get('email'),
            }
            
            # Add optional fields if they exist
            if body.get('sid'):
                cleaned_body['sid'] = body.get('sid')
            if body.get('school'):
                cleaned_body['school'] = body.get('school')
            if body.get('kasm_server_needed') is not None:
                cleaned_body['kasm_server_needed'] = body.get('kasm_server_needed')
            # Support assigning classes (e.g. ["CSSE","CSP","CSA"]).
            # Accept either a list or a single string.
            if body.get('class') is not None:
                cleaned_body['class'] = body.get('class')
            if body.get('game_profile') is not None:
                cleaned_body['game_profile'] = body.get('game_profile')
            
            # Remove None values
            cleaned_body = {k: v for k, v in cleaned_body.items() if v is not None}
            
            # print(f"Cleaned body for user creation: {cleaned_body}")

            #2: Save the User object to the database using custom create method
            try:
                user = user_obj.create(cleaned_body) # pass the cleaned body elements to be saved in the database
                #print(f"Create method returned: {user}")
                #print(f"User type: {type(user)}")
                
                if not user:
                    # Check if user was actually created in database despite create() returning None
                    db_user = User.query.filter_by(_uid=uid).first()
                    if db_user:
                        #print(f"User exists in DB but create returned None: {db_user.uid}")
                        return jsonify(db_user.read())  # Return the user anyway
                    else:
                        return {'message': f'Processed {name}, either a format error or User ID {uid} is duplicate'}, 400
                
                #print(f"Successfully created user: {user.uid}")
                # return response, the created user details as a JSON object
                return jsonify(user.read())
                
            except Exception as e:
                #print(f"Error creating user: {e}")
                return {'message': f'Error creating user: {str(e)}'}, 500

        @token_required()
        def get(self):
            """
            Retrieve all users.

            Retrieves a list of all users in the database.
            
            Query Parameters:
                page (int): Page number for pagination (starts at 1)
                per_page (int): Number of users per page (default: 50, max: 200)

            Returns:
                JSON response with a list of user dictionaries.
            """
            # retrieve the current user from the token_required authentication check  
            current_user = g.current_user
            
            # Get query parameters for pagination
            page = request.args.get('page', type=int)
            per_page = min(request.args.get('per_page', 50, type=int), 200)
            
            """ User SQLAlchemy query returning list of all users """
            if page:
                # Paginated query
                pagination = User.query.paginate(page=page, per_page=per_page, error_out=False)
                users = pagination.items
                has_next = pagination.has_next
                has_prev = pagination.has_prev
                total = pagination.total
            else:
                users = User.query.all() # extract all users from the database
                has_next = False
                has_prev = False
                total = len(users)
             
            # prepare a json list of user dictionaries
            json_ready = []  
            for user in users:
                user_data = user.read()
                # Add access control
                if current_user.role == 'Admin' or current_user.id == user.id:
                    user_data['access'] = ['rw'] # read-write access control 
                else:
                    user_data['access'] = ['ro'] # read-only access control 
                json_ready.append(user_data)
            
            # return response, a list of user dictionaries in JSON format
            if page:
                return jsonify({
                    'users': json_ready,
                    'pagination': {
                        'page': page,
                        'per_page': per_page,
                        'total': total,
                        'has_next': has_next,
                        'has_prev': has_prev
                    }
                })
            else:
                return jsonify(json_ready)
        
        @token_required()
        def put(self):
            """
            Update user details.

            Retrieves the current user from the token_required authentication check and updates the user details based on the JSON body of the request.

            Returns:
                JSON response with the updated user details or an error message.
            """
            
            # Retrieve the current user from the token_required authentication check
            current_user = g.current_user
            # Read data from the JSON body of the request
            body = request.get_json()

            ''' Admin-specific update handling '''
            if current_user.role == 'Admin':
                uid = body.get('uid')
                # Admin is updating themself
                if uid is None or uid == current_user.uid:
                    user = current_user 
                else: # Admin is updating another user
                    """ User SQLAlchemy query returning a single user """
                    user = User.query.filter_by(_uid=uid).first()
                    if user is None:
                        return {'message': f'User {uid} not found'}, 404
            else:
                # Non-admin can only update themselves
                user = current_user
                
            # Accounts are desired to be GitHub accounts, change must be validated 
            if body.get('uid') and body.get('uid') != user._uid:
                _, status = GitHubUser().get(body.get('uid'))
                if status != 200:
                    return {'message': f'User ID {body.get("uid")} not a valid GitHub account' }, 404
            
            # Update the User object to the database using custom update method
            user.update(body)
            
            # return response, the updated user details as a JSON object
            return jsonify(user.read())
        
        @token_required("Admin")
        def delete(self):
            """
            Delete a user.

            Deletes a user from the database based on the JSON body of the request. Only accessible by Admin users.

            Returns:
                JSON response with a success message or an error message.
            """
            body = request.get_json()
            uid = body.get('uid')
            
            """ User SQLAlchemy query returning a single user """
            user = User.query.filter_by(_uid=uid).first()
            
            # bad request
            if user is None:
                return {'message': f'User {uid} not found'}, 404
           
            # Read and then Delete the User object using custom methods
            user_json = user.read()
            user.delete()
            
            # 204 is the status code for delete with no json response
            return f"Deleted user: {user_json}", 204 # use 200 to test with Postman
         
    class _Section(Resource):  # Section API operation
        @token_required()
        def get(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            ''' Return the current user as a json object '''
            return jsonify(current_user.read_sections())
       
        @token_required() 
        def post(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
            
            ''' Read data for json body '''
            body = request.get_json()
            
            ''' Error checking '''
            sections = body.get('sections')
            if sections is None or len(sections) == 0:
                return {'message': f"No sections to add were provided"}, 400
            
            ''' Add sections'''
            if not current_user.add_sections(sections):
                return {'message': f'1 or more sections failed to add, current {sections} requested {current_user.read_sections()}'}, 404
            
            return jsonify(current_user.read_sections())
        
        @token_required()
        def put(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user

            ''' Read data for json body '''
            body = request.get_json()

            ''' Error checking '''
            section_data = body.get('section')
            if not section_data:
                return {'message': 'Section data is required'}, 400
            
            if not section_data.get('abbreviation'):
                return {'message': 'Section abbreviation is required'}, 400
            
            if not section_data.get('year'):
                return {'message': 'Section year is required'}, 400

            ''' Update section year '''
            if not current_user.update_section(section_data):
                return {'message': f'Section {section_data.get("abbreviation")} not found or update failed'}, 404

            return jsonify(current_user.read_sections())
        
        @token_required()
        def delete(self):
            ''' Retrieve the current user from the token_required authentication check '''
            current_user = g.current_user
    
            ''' Read data for json body '''
            body = request.get_json()
    
            ''' Error checking '''
            sections = body.get('sections')
            if sections is None or len(sections) == 0:
                return {'message': f"No sections to delete were provided"}, 400
    
            ''' Remove sections '''
            if not current_user.remove_sections(sections):
                return {'message': f'1 or more sections failed to delete, current {sections} requested {current_user.read_sections()}'}, 404
    
            return {'message': f'Sections {sections} deleted successfully'}, 200
    class _Security(Resource):
        def post(self):
            try:
                body = request.get_json()
                if not body:
                    return {
                        "message": "Please provide user details",
                        "data": None,
                        "error": "Bad request"
                    }, 400
                ''' Get Data '''
                uid = body.get('uid')
                if uid is None:
                    return {'message': f'User ID is missing'}, 401
                password = body.get('password')
                if not password:
                    return {'message': f'Password is missing'}, 401
                            
                ''' Find user '''
    
                user = User.query.filter_by(_uid=uid).first()
                
                if user is None or not user.is_password(password):
                    
                    return {'message': f"Invalid user id or password"}, 401
                            
                # Check if user is found
                if user:
                    try:
                        token = jwt.encode(
                            {"_uid": user._uid},
                            current_app.config["SECRET_KEY"],
                            algorithm="HS256"
                        )
                        # Return JSON response with cookie
                        is_production = os.environ.get('IS_PRODUCTION', 'false').lower() == 'true'
                        
                        # Create JSON response
                        response_data = {
                            "message": f"Authentication for {user._uid} successful",
                            "user": {
                                "uid": user._uid,
                                "name": user.name,
                                "role": user.role,
                                "class": user._class if getattr(user, '_class', None) is not None else []
                            }
                        }
                        resp = jsonify(response_data)
                        
                        # Set cookie
                        if is_production:
                            resp.set_cookie(
                                current_app.config["JWT_TOKEN_NAME"],
                                token,
                                max_age=43200,  # 12 hours in seconds
                                secure=True,
                                httponly=True,
                                path='/',
                                samesite='None',
                                domain='.opencodingsociety.com'
                            )
                        else:
                            resp.set_cookie(
                                current_app.config["JWT_TOKEN_NAME"],
                                token,
                                max_age=43200,  # 12 hours in seconds
                                secure=False,
                                httponly=False,  # Set to True for more security if JS access not needed
                                path='/',
                                samesite='Lax'
                            )
                        print(f"Token set: {token}")
                        return resp 
                    except Exception as e:
                        return {
                                        "error": "Something went wrong",
                                        "message": str(e)
                                    }, 500
                return {
                                "message": "Error fetching auth token!",
                                "data": None,
                                "error": "Unauthorized"
                            }, 404
            except Exception as e:
                 return {
                                "message": "Something went wrong!",
                                "error": str(e),
                                "data": None
                            }, 500
                 
        @token_required()
        def delete(self):
            ''' Invalidate the current user's token by setting its expiry to 0 '''
            current_user = g.current_user
            try:
                # Generate a token with practically 0 age
                token = jwt.encode(
                    {"_uid": current_user._uid, 
                     "exp": datetime.utcnow()},
                    current_app.config["SECRET_KEY"],
                    algorithm="HS256"
                )
                # You might want to log this action or take additional steps here
                
                # Prepare a response indicating the token has been invalidated
                resp = Response("Token invalidated successfully")
                is_production = os.environ.get('IS_PRODUCTION', 'false').lower() == 'true'
                if is_production:
                    resp.set_cookie(
                        current_app.config["JWT_TOKEN_NAME"],
                        token,
                        max_age=0,  # Immediately expire the cookie
                        secure=True,
                        httponly=True,
                        path='/',
                        samesite='None',
                        domain='.opencodingsociety.com'
                
                    )
                else:
                    resp.set_cookie(
                        current_app.config["JWT_TOKEN_NAME"],
                        token,
                        max_age=0,  # Immediately expire the cookie
                        secure=False,
                        httponly=False,  # Set to True for more security if JS access not needed
                        path='/',
                        samesite='Lax'
                    )
                return resp
            except Exception as e:
                return {
                    "message": "Failed to invalidate token",
                    "error": str(e)
                }, 500

    class _GradeData(Resource):
        """
        Grade data API operations
        """
        
        @token_required()
        def get(self):
            """
            Get the grade data for a user.
            """
            current_user = g.current_user
            
            # If request includes a UID parameter and user is admin, get that user's grade data
            uid = request.args.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user  # Get the current user's grade data
                
            return jsonify({'uid': user.uid, 'grade_data': user.grade_data})
        
        @token_required()
        def post(self):
            """
            Add or update grade data for a user.
            """
            current_user = g.current_user
            body = request.get_json()
            
            # Determine which user's grade data to update
            uid = body.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                # Non-admins can only update their own grade data
                if uid and uid != current_user.uid and current_user.role != 'Admin':
                    return {'message': 'Permission denied: You can only update your own grade data'}, 403
                user = current_user
            
            # Get the grade data from the request
            grade_data = body.get('grade_data')
            if not grade_data:
                return {'message': 'Grade data is missing'}, 400
                
            # Update the user's grade data
            user.update({'grade_data': grade_data})
            
            return jsonify({'message': 'Grade data updated successfully', 'uid': user.uid, 'grade_data': user.grade_data})

    class _APExam(Resource):
        """
        AP exam data API operations
        """
        
        @token_required()
        def get(self):
            """
            Get the AP exam data for a user.
            """
            current_user = g.current_user
            
            # If request includes a UID parameter and user is admin, get that user's AP exam data
            uid = request.args.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user  # Get the current user's AP exam data
                
            return jsonify({'uid': user.uid, 'ap_exam': user.ap_exam})
        
        @token_required()
        def post(self):
            """
            Add or update AP exam data for a user.
            """
            current_user = g.current_user
            body = request.get_json()
            
            # Determine which user's AP exam data to update
            uid = body.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                # Non-admins can only update their own AP exam data
                if uid and uid != current_user.uid and current_user.role != 'Admin':
                    return {'message': 'Permission denied: You can only update your own AP exam data'}, 403
                user = current_user
            
            # Get the AP exam data from the request
            ap_exam = body.get('ap_exam')
            if not ap_exam:
                return {'message': 'AP exam data is missing'}, 400
                
            # Update the user's AP exam data
            user.update({'ap_exam': ap_exam})
            
            return jsonify({'message': 'AP exam data updated successfully', 'uid': user.uid, 'ap_exam': user.ap_exam})

    class _School(Resource):
        """
        School data API operations
        """

        @token_required()
        def get(self):
            """
            Get the school data for a user.
            """
            current_user = g.current_user

            # If request includes a UID parameter and user is admin, get that user's school data
            uid = request.args.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user  # Get the current user's school data

            return jsonify({'uid': user.uid, 'school': user.school})

        @token_required()
        def post(self):
            """
            Add or update school data for a user.
            """
            current_user = g.current_user
            body = request.get_json()

            # Determine which user's school data to update
            uid = body.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                # Non-admins can only update their own school data
                if uid and uid != current_user.uid and current_user.role != 'Admin':
                    return {'message': 'Permission denied: You can only update your own school data'}, 403
                user = current_user

            # Get the school data from the request
            school = body.get('school')
            if not school:
                return {'message': 'School data is missing'}, 400

            # Update the user's school data
            user.update({'school': school})

            return jsonify({'message': 'School data updated successfully', 'uid': user.uid, 'school': user.school})

    class _GuestCRUD(Resource):
        """
        Guest user API operations - simplified signup without GitHub validation
        """

        def post(self):
            """
            Create a new guest user account.

            Accepts only username (uid) and password. Auto-generates required fields.
            No GitHub validation required for guest accounts.

            Returns:
                JSON response with the created user details or an error message.
            """
            # Read data from json body
            body = request.get_json()

            # Validate uid (username)
            uid = body.get('uid')
            if uid is None or len(uid) < 2:
                return {'message': 'Username is missing, or is less than 2 characters'}, 400

            # Validate password (relaxed requirement for guests)
            password = body.get('password')
            if password is None or len(password) < 2:
                return {'message': 'Password is missing, or is less than 2 characters'}, 400

            # Auto-generate required fields for guest accounts
            name = f"Guest_{uid}"
            email = "?"
            sid = "?"
            school = "?"

            # Create User object with auto-generated name
            user_obj = User(name=name, uid=uid, password=password)

            # Build cleaned body with all fields filled
            cleaned_body = {
                'name': name,
                'uid': uid,
                'password': password,
                'email': email,
                'sid': sid,
                'school': school,
                'kasm_server_needed': False
            }
            if body.get('class') is not None:
                cleaned_body['class'] = body.get('class')

            # Create the guest user (skip GitHub validation)
            try:
                user = user_obj.create(cleaned_body)

                if not user:
                    # Check if user was actually created in database
                    db_user = User.query.filter_by(_uid=uid).first()
                    if db_user:
                        return jsonify(db_user.read())
                    else:
                        return {'message': f'Failed to create guest account for {uid}, username may already exist'}, 400

                # Return the created user details
                return jsonify(user.read())

            except Exception as e:
                return {'message': f'Error creating guest user: {str(e)}'}, 500

    # building RESTapi endpoint
    api.add_resource(_ID, '/id')
    api.add_resource(_BULK, '/users')
    api.add_resource(_CRUD, '/user')
    api.add_resource(_GuestCRUD, '/user/guest')
    api.add_resource(_Section, '/user/section')
    api.add_resource(_Security, '/authenticate')
    api.add_resource(_GradeData, '/grade_data')
    api.add_resource(_APExam, '/apexam')
    api.add_resource(_School, '/school')
    
    class _Class(Resource):
        """Manage the user's `class` list (e.g. CSSE, CSP, CSA).
        GET: return classes
        POST: add or remove classes (use 'action' parameter: 'add', 'remove', or 'clear')
        PUT: replace classes
        """

        @token_required()
        def get(self):
            current_user = g.current_user
            uid = request.args.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user

            return jsonify({'uid': user.uid, 'class': user._class if getattr(user, '_class', None) is not None else []})

        @token_required()
        def post(self):
            """Add, remove, or clear classes from the user's class list based on action parameter."""
            current_user = g.current_user
            body = request.get_json() or {}
            uid = body.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user

            action = body.get('action', 'add')  # Default to 'add' for backward compatibility
            
            if action == 'clear':
                # Clear all classes
                user.update({'class': []})
                return {'message': f'Cleared classes for {user.uid}'}, 200
            
            classes = body.get('class') or body.get('classes')
            if not classes:
                return {'message': f'No classes provided to {action}'}, 400

            if isinstance(classes, str):
                classes = [classes]

            existing = user._class if getattr(user, '_class', None) is not None else []
            
            if action == 'add':
                # Add classes (merge without duplicates)
                new_list = existing + [c for c in classes if c not in existing]
                user.update({'class': new_list})
                return jsonify({'uid': user.uid, 'class': user._class})
            
            elif action == 'remove':
                # Remove specified classes
                remaining = [c for c in existing if c not in classes]
                user.update({'class': remaining})
                return jsonify({'uid': user.uid, 'class': user._class})
            
            else:
                return {'message': f'Invalid action: {action}. Use "add", "remove", or "clear"'}, 400

        @token_required()
        def put(self):
            """Replace the user's class list with the provided list."""
            current_user = g.current_user
            body = request.get_json() or {}
            uid = body.get('uid')
            if current_user.role == 'Admin' and uid:
                user = User.query.filter_by(_uid=uid).first()
                if not user:
                    return {'message': f'User {uid} not found'}, 404
            else:
                user = current_user

            classes = body.get('class') or body.get('classes')
            if classes is None:
                return {'message': 'class list is required for PUT'}, 400
            if isinstance(classes, str):
                classes = [classes]

            user.update({'class': classes})
            return jsonify({'uid': user.uid, 'class': user._class})



    api.add_resource(_Class, '/user/class')