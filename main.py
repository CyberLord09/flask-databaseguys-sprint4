# imports from flask
from datetime import datetime
from urllib.parse import urljoin, urlparse
from flask import abort, redirect, render_template, request, send_from_directory, url_for, jsonify, current_app, g # import render_template from "public" flask libraries
from flask_login import current_user, login_user, logout_user
from flask.cli import AppGroup
from flask_login import current_user, login_required
from flask import current_app
from dotenv import load_dotenv

# import "objects" from "this" project
from __init__ import app, db, login_manager  # Key Flask objects 
from model.persona import Persona, initPersonas, initPersonaUsers
# API endpoints
from api.user import user_api 
from api.python_exec_api import python_exec_api
from api.javascript_exec_api import javascript_exec_api
from api.section import section_api
from api.persona_api import persona_api
from api.skill_snapshot_api import skill_passport_api
from api.pfp import pfp_api
from api.analytics import analytics_api
from api.student import student_api
from api.groq_api import groq_api
from api.gemini_api import gemini_api
from api.ainpc_api import ainpc_api
from api.microblog_api import microblog_api
from api.classroom_api import classroom_api
from api.data_export_import_api import data_export_import_api
from api.leaderboard import dynamic_api, events_api
from hacks.joke import joke_api  # Import the joke API blueprint
from api.post import post_api  # Import the social media post API
from api.profile_game import profile_game_api  # CS Pathway Game profile persistence
from api.snapshot_proxy import snapshot_proxy
#from api.announcement import announcement_api ##temporary revert

# database Initialization functions
from model.user import User, initUsers
from model.user import Section;
from model.github import GitHubUser
from model.feedback import Feedback
from api.analytics import get_date_range
# from api.grade_api import grade_api
from api.study import study_api
from api.feedback_api import feedback_api
from model.study import Study, initStudies
from model.classroom import Classroom
from model.skill_snapshot import SkillSnapshot
from model.post import Post, init_posts
from model.microblog import MicroBlog, Topic, initMicroblogs
from model.leaderboard import ScoreCounterEvent, ElementaryLeaderboardEvent
from hacks.jokes import initJokes 
# from model.announcement import Announcement ##temporary revert

# server only Views

import os
import requests

# Load environment variables
load_dotenv()

app.config['KASM_SERVER'] = os.getenv('KASM_SERVER')
app.config['KASM_API_KEY'] = os.getenv('KASM_API_KEY')
app.config['KASM_API_KEY_SECRET'] = os.getenv('KASM_API_KEY_SECRET')

from flask_cors import CORS
CORS(app)  # This allows all origins, your frontend can now call /api/ainpc/prompt



# register URIs for api endpoints
app.register_blueprint(python_exec_api)
app.register_blueprint(javascript_exec_api)
app.register_blueprint(user_api)
app.register_blueprint(section_api)
app.register_blueprint(persona_api)
app.register_blueprint(skill_passport_api)
app.register_blueprint(pfp_api) 
app.register_blueprint(groq_api)
app.register_blueprint(gemini_api)
app.register_blueprint(ainpc_api)
app.register_blueprint(microblog_api)
app.register_blueprint(analytics_api)
app.register_blueprint(student_api)
# app.register_blueprint(grade_api)
app.register_blueprint(study_api)
app.register_blueprint(classroom_api)
app.register_blueprint(feedback_api)
app.register_blueprint(data_export_import_api)  # Register the data export/import API
app.register_blueprint(dynamic_api)  # Register the dynamic leaderboard API
app.register_blueprint(events_api)  # Register the elementary leaderboard API
app.register_blueprint(joke_api)  # Register the joke API blueprint
app.register_blueprint(post_api)  # Register the social media post API
app.register_blueprint(profile_game_api)  # CS Pathway Game profile persistence
app.register_blueprint(snapshot_proxy)  # Register the snapshot proxy API
# app.register_blueprint(announcement_api) ##temporary revert

# Jokes file initialization
with app.app_context():
    initJokes()

# Tell Flask-Login the view function name of your login route
login_manager.login_view = "login"

@login_manager.unauthorized_handler
def unauthorized_callback():
    return redirect(url_for('login', next=request.path))

# register URIs for server pages
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

# Helper function to check if the URL is safe for redirects
def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    next_page = request.args.get('next', '') or request.form.get('next', '')
    if request.method == 'POST':
        user = User.query.filter_by(_uid=request.form['username']).first()
        if user and user.is_password(request.form['password']):
            login_user(user)
            if not is_safe_url(next_page):
                return abort(400)
            return redirect(next_page or url_for('index'))
        else:
            error = 'Invalid username or password.'
    return render_template("login.html", error=error, next=next_page)

@app.route('/studytracker')  # route for the study tracker page
def studytracker():
    return render_template("studytracker.html")
    
@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.errorhandler(404)  # catch for URL not found
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template('404.html'), 404

@app.route('/')  # connects default URL to index() function
def index():
    print("Home:", current_user)
    return render_template("index.html")



@app.route('/users/table2')
@login_required
def u2table():
    users = User.query.all()
    return render_template("u2table.html", user_data=users)

@app.route('/sections/')
@login_required
def sections():
    sections = Section.query.all()
    return render_template("sections.html", sections=sections)

@app.route('/persona/')
@login_required
def persona():
    personas = Persona.query.all()
    return render_template("persona.html", personas=personas)

# Helper function to extract uploads for a user (ie PFP image)
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
 
@app.route('/users/delete/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if user:
        user.delete()
        return jsonify({'message': 'User deleted successfully'}), 200
    return jsonify({'error': 'User not found'}), 404

@app.route('/users/reset_password/<int:user_id>', methods=['POST'])
@login_required
def reset_password(user_id):
    if current_user.role != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Set the new password
    if user.update({"password": app.config['DEFAULT_PASSWORD']}):
        return jsonify({'message': 'Password reset successfully'}), 200
    return jsonify({'error': 'Password reset failed'}), 500

@app.route('/kasm_users')
def kasm_users():
    # Fetch configuration details from environment or app config
    SERVER = current_app.config.get('KASM_SERVER')
    API_KEY = current_app.config.get('KASM_API_KEY')
    API_KEY_SECRET = current_app.config.get('KASM_API_KEY_SECRET')

    # Validate required configurations
    if not SERVER or not API_KEY or not API_KEY_SECRET:
        return render_template('error.html', message='KASM keys are missing'), 400

    try:
        # Prepare API request details
        url = f"{SERVER}/api/public/get_users"
        data = {
            "api_key": API_KEY,
            "api_key_secret": API_KEY_SECRET
        }

        # Perform the POST request
        response = requests.post(url, json=data, timeout=10)  # Added timeout for reliability

        # Validate the API response
        if response.status_code != 200:
            return render_template(
                'error.html', 
                message='Failed to get users', 
                code=response.status_code
            ), response.status_code

        # Parse the users list from the response
        users = response.json().get('users', [])

        # Process `last_session` and handle potential parsing issues
        for user in users:
            last_session = user.get('last_session')
            try:
                user['last_session'] = datetime.fromisoformat(last_session) if last_session else None
            except ValueError:
                user['last_session'] = None  # Fallback for invalid date formats

        # Sort users by `last_session`, treating `None` as the oldest date
        sorted_users = sorted(
            users, 
            key=lambda x: x['last_session'] or datetime.min, 
            reverse=True
        )

        # Render the sorted users in the template
        return render_template('kasm_users.html', users=sorted_users)

    except requests.RequestException as e:
        # Handle connection errors or other request exceptions
        return render_template(
            'error.html', 
            message=f"Error connecting to KASM API: {str(e)}"
        ), 500
        
        
@app.route('/delete_user/<user_id>', methods=['DELETE'])
def delete_user_kasm(user_id):
    if current_user.role != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    SERVER = current_app.config.get('KASM_SERVER')
    API_KEY = current_app.config.get('KASM_API_KEY')
    API_KEY_SECRET = current_app.config.get('KASM_API_KEY_SECRET')

    if not SERVER or not API_KEY or not API_KEY_SECRET:
        return {'message': 'KASM keys are missing'}, 400

    try:
        # Kasm API to delete a user
        url = f"{SERVER}/api/public/delete_user"
        data = {
            "api_key": API_KEY,
            "api_key_secret": API_KEY_SECRET,
            "target_user": {"user_id": user_id},
            "force": False
        }
        response = requests.post(url, json=data)

        if response.status_code == 200:
            return {'message': 'User deleted successfully'}, 200
        else:
            return {'message': 'Failed to delete user'}, response.status_code

    except requests.RequestException as e:
        return {'message': 'Error connecting to KASM API', 'error': str(e)}, 500


@app.route('/update_user/<string:uid>', methods=['PUT'])
def update_user(uid):
    # Authorization check
    if current_user.role != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Get the JSON data from the request
    data = request.get_json()
    print(f"Request Data: {data}")  # Log the incoming data

    # Find the user in the database
    user = User.query.filter_by(_uid=uid).first()
    if user:
        print(f"Found user: {user.uid}")  # Log the found user's UID
        
        # Update the user using the provided data
        user.update(data)  # Assuming `user.update(data)` is a method on your User model
        
        # Save changes to the database
        return jsonify({"message": "User updated successfully."}), 200
    else:
        print("User not found.")  # Log when user is not found
        return jsonify({"message": "User not found."}), 404



    
# Create an AppGroup for custom commands
custom_cli = AppGroup('custom', help='Custom commands')

# Define a command to run the data generation functions
@custom_cli.command('generate_data')
def generate_data():
    initUsers()
    initMicroblogs()
    initPersonas()
    initPersonaUsers()

# Register the custom command group with the Flask application
app.cli.add_command(custom_cli)
        
# this runs the flask application on the development server
if __name__ == "__main__":
    host = "0.0.0.0"
    port = app.config['FLASK_PORT']
    print(f"** Server running: http://localhost:{port}")  # Pretty link
    app.run(debug=True, host=host, port=port, use_reloader=False)
