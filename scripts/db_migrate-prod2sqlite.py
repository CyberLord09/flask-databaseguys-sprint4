#!/usr/bin/env python3

""" db_migrate-prod2sqlite.py
Migrates ALL data from production database to local SQLite.

This script:
1. Authenticates to production server
2. Exports ALL data using /api/export/all endpoint (users, microblogs, posts, etc.)
3. Saves exported data to instance/data.json as backup
4. Runs db init (db.create_all() + initUsers()) on local database
5. Loads the exported data INTO the local database

Usage:
> cd scripts; ./db_migrate-prod2sqlite.py
or
> python scripts/db_migrate-prod2sqlite.py

"""
import shutil
import sys
import os
import requests
import subprocess
import json
import time
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# Add the directory containing main.py to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Import application object
from main import app, db, initUsers

# Base URL for production server
BASE_URL = "https://flask.opencodingsociety.com"

# API Endpoint for comprehensive data export
# API Endpoints for chunked data export (one per data type)
EXPORT_ENDPOINTS = {
    'sections': '/api/export/sections',
    'users': '/api/export/users',
    'topics': '/api/export/topics',
    'microblogs': '/api/export/microblogs',
    'posts': '/api/export/posts',
    'classrooms': '/api/export/classrooms',
    'feedback': '/api/export/feedback',
    'study': '/api/export/study',
    'personas': '/api/export/personas',
    'user_personas': '/api/export/user_personas',
}

# Locations and credentials
AUTH_URL = BASE_URL + "/api/authenticate"
# Use ADMIN credentials - export requires Admin privileges
UID = app.config['ADMIN_UID']
PASSWORD = app.config['ADMIN_PASSWORD']

PERSISTENCE_PREFIX = "instance"
JSON_DATA = PERSISTENCE_PREFIX + "/data.json"

# Default data to EXCLUDE from migration (created by initUsers, init_posts, etc.)
# These are recreated when db.create_all() runs, so we don't want duplicates
DEFAULT_DATA = {
    'users': [
        app.config.get('ADMIN_UID', 'admin'),
        app.config.get('DEFAULT_UID', 'user'),
        'niko',  # Nicholas Tesla test user
    ],
    'sections': [
        'CSA',      # Computer Science A
        'CSP',      # Computer Science Principles
        'Robotics', # Engineering Robotics
        'CSSE',     # Computer Science and Software Engineering
    ],
    'topics': [
        '/lessons/flask-introduction',
        '/hacks/javascript-basics',
        '/projects/portfolio-showcase',
        '/general/daily-standup',
        '/resources/study-materials',
    ],
    # Posts and microblogs from init functions are tied to default users
    # We'll filter by user_id/uid matching default users
}

# Backup the old database
def backup_database(db_uri, backup_uri, db_string):
    """Backup the current database."""
    db_name = db_uri.split('/')[-1]
    backup_file = f"{db_name}_backup.sql"   
    if 'mysql' in db_string:
        os.environ['MYSQL_PWD'] = app.config["DB_PASSWORD"]
        try:
            subprocess.run([
                'mysqldump',
                '-h', app.config["DB_ENDPOINT"],
                '-u', app.config["DB_USERNAME"],
                f'-p{app.config["DB_PASSWORD"]}',
                db_name,
                '>', backup_file
            ], check=True, shell=True)
            print(f"MySQL database backed up to {backup_file}")
        except subprocess.CalledProcessError as e:
            print(f"Backup tool mysqldump not working or installed {e}")
        finally:
            del os.environ['MYSQL_PWD']
    elif 'sqlite' in db_string:
        # SQLite backup using shutil
        if backup_uri:
            db_path = db_uri.replace('sqlite:///', PERSISTENCE_PREFIX + '/') 
            backup_path = backup_uri.replace('sqlite:///', PERSISTENCE_PREFIX + '/') 
            shutil.copyfile(db_path, backup_path)
            print(f"SQLite database backed up to {backup_path}")
        else:
            print("Backup not supported for production database.")
    else:
        print("Unsupported database type for backup.")

# Create the database if it does not exist
def create_database(engine, db_name):
    """Create the database if it does not exist."""
    with engine.connect() as connection:
        result = connection.execute(text(f"SHOW DATABASES LIKE '{db_name}'"))
        if not result.fetchone():
            connection.execute(text(f"CREATE DATABASE {db_name}"))
            print(f"Database '{db_name}' created successfully.")
        else:
            print(f"Database '{db_name}' already exists.")

# Old data access        
def authenticate(uid, password):
    '''Authenticate and return the token/cookies'''
    auth_data = {
        "uid": uid,
        "password": password
    }
    headers = {
        "Content-Type": "application/json",
        "X-Origin": "client"
    }
    try:
        response = requests.post(AUTH_URL, json=auth_data, headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.cookies, None
    except requests.RequestException as e:
        return None, {'message': 'Failed to authenticate', 'code': getattr(response, 'status_code', 0), 'error': str(e)}

# Extract ALL data from production using chunked endpoints (one per data type)
def extract_all_data(cookies):
    '''Extract all data using paginated endpoints to avoid timeout.

    All endpoints now use pagination with 50 records per page.
    This ensures consistent, predictable performance regardless of dataset size.
    '''
    print("  Using paginated export endpoints (50 records per page)...")

    headers = {
        "Content-Type": "application/json",
        "X-Origin": "client"
    }

    all_data = {}
    total_records = 0
    failed_endpoints = []

    # Data types that need pagination (large datasets)
    paginated_types = ['users', 'microblogs', 'posts', 'topics', 'personas', 'user_personas']

    for data_type, endpoint in EXPORT_ENDPOINTS.items():
        url = BASE_URL + endpoint
        print(f"  Fetching {data_type}...", end=" ", flush=True)

        try:
            # Use pagination for data types that can be large
            if data_type in paginated_types:
                all_records = []
                page = 1
                per_page = 50
                max_retries = 3

                while True:
                    paginated_url = f"{url}?page={page}&per_page={per_page}"
                    retry_count = 0
                    success = False

                    # Retry logic for failed requests
                    while retry_count < max_retries and not success:
                        try:
                            response = requests.get(paginated_url, headers=headers, cookies=cookies, timeout=180)

                            if response.status_code not in [200, 201]:
                                error_msg = f"HTTP {response.status_code}"
                                try:
                                    error_data = response.json()
                                    if 'message' in error_data:
                                        error_msg += f": {error_data['message']}"
                                except:
                                    error_msg += f": {response.text[:100]}"

                                # Retry on 504 (Gateway Timeout)
                                if response.status_code == 504:
                                    retry_count += 1
                                    if retry_count < max_retries:
                                        print(f"R", end="", flush=True)  # R for retry
                                        time.sleep(2)
                                        continue

                                print(f"\nFAILED on page {page} ({error_msg})")
                                failed_endpoints.append((data_type, error_msg))
                                break

                            result = response.json()
                            page_records = result.get(data_type, [])
         
                            # Safety check: stop if no records returned
                            if len(page_records) == 0:
                                break
         
                            all_records.extend(page_records)
                            success = True

                            # Print progress dot
                            print(f".", end="", flush=True)

                            # Check if there are more pages
                            if not result.get('has_next', False):
                                break

                        except requests.Timeout:
                            retry_count += 1
                            if retry_count < max_retries:
                                print(f"T", end="", flush=True)  # T for timeout retry
                                time.sleep(2)
                                continue
                            else:
                                print(f"\nTIMEOUT on page {page} after {max_retries} retries")
                                failed_endpoints.append((data_type, "Request timed out"))
                                break

                        except requests.RequestException as e:
                            print(f"\nERROR on page {page}: {str(e)[:50]}")
                            failed_endpoints.append((data_type, str(e)))
                            break

                    if not success:
                        break

                    page += 1

                all_data[data_type] = all_records
                total_records += len(all_records)
                print(f" {len(all_records)} records ({page} page(s))")

            else:
                # Regular single-request fetch for small datasets (sections, classrooms, feedback, study)
                response = requests.get(url, headers=headers, cookies=cookies, timeout=120)

                if response.status_code not in [200, 201]:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_data = response.json()
                        if 'message' in error_data:
                            error_msg += f": {error_data['message']}"
                    except:
                        error_msg += f": {response.text[:100]}"

                    print(f"FAILED ({error_msg})")
                    failed_endpoints.append((data_type, error_msg))
                    continue

                result = response.json()

                # Extract the data array
                if data_type in result:
                    records = result[data_type]
                    all_data[data_type] = records
                    count = len(records) if isinstance(records, list) else 1
                    total_records += count
                    print(f"{count} records")
                else:
                    print("no data found in response")
                    all_data[data_type] = []

        except requests.Timeout:
            print(f"TIMEOUT")
            failed_endpoints.append((data_type, "Request timed out"))
        except requests.RequestException as e:
            print(f"ERROR ({str(e)[:50]})")
            failed_endpoints.append((data_type, str(e)))

    # Add metadata
    all_data['_metadata'] = {
        'total_records': total_records,
        'tables': list(EXPORT_ENDPOINTS.keys()),
        'failed_endpoints': failed_endpoints
    }

    print(f"\n  Total records extracted: {total_records}")

    if failed_endpoints:
        print(f"  WARNING: {len(failed_endpoints)} endpoint(s) failed:")
        for data_type, error in failed_endpoints:
            print(f"    - {data_type}: {error}")

        # If critical endpoints failed (users, sections), return error
        critical = ['users', 'sections']
        critical_failed = [dt for dt, _ in failed_endpoints if dt in critical]
        if critical_failed:
            return None, {
                'message': f'Critical endpoints failed: {", ".join(critical_failed)}',
                'code': 500,
                'error': 'Cannot proceed without users and sections data'
            }

    return all_data, None
    
# Write data to JSON file
def write_data_to_json(data, json_file):
    """Write data to JSON file and create a timestamped backup if the file exists."""
    if os.path.exists(json_file):
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        backup_file = f"{json_file}.{timestamp}.bak"
        shutil.copyfile(json_file, backup_file)
        print(f"Existing JSON data backed up to {backup_file}")
    
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"Data written to {json_file}")

# Read data from JSON file
def read_data_from_json(json_file):
    """Read data from JSON file."""
    if os.path.exists(json_file):
        with open(json_file, 'r') as f:
            return json.load(f), None
    else:
        return None, {'message': 'JSON data file not found', 'code': 404, 'error': 'File not found'}


# === Data Loading Functions ===

def is_default_user(uid):
    """Check if a user is a default/test user that should be skipped."""
    return uid in DEFAULT_DATA['users']

def is_default_section(abbreviation):
    """Check if a section is a default one that should be skipped."""
    return abbreviation in DEFAULT_DATA['sections']

def is_default_topic(page_path):
    """Check if a topic is a default one that should be skipped."""
    return page_path in DEFAULT_DATA['topics']

def filter_default_data(all_data):
    """Filter out default/test data that gets created by init functions."""
    filtered = {}

    # Filter users - exclude default users
    users = all_data.get('users', [])
    if users:
        filtered['users'] = [u for u in users if not is_default_user(u.get('uid'))]
        skipped = len(users) - len(filtered['users'])
        if skipped > 0:
            print(f"  Filtered out {skipped} default users")

    # Filter sections - exclude default sections
    sections = all_data.get('sections', [])
    if sections:
        filtered['sections'] = [s for s in sections if not is_default_section(s.get('abbreviation'))]
        skipped = len(sections) - len(filtered['sections'])
        if skipped > 0:
            print(f"  Filtered out {skipped} default sections")

    # Filter topics - exclude default topics
    topics = all_data.get('topics', [])
    if topics:
        page_path_key = 'pagePath' if topics and 'pagePath' in topics[0] else 'page_path'
        filtered['topics'] = [t for t in topics if not is_default_topic(t.get(page_path_key) or t.get('page_path'))]
        skipped = len(topics) - len(filtered['topics'])
        if skipped > 0:
            print(f"  Filtered out {skipped} default topics")

    # Filter microblogs - exclude those from default users
    microblogs = all_data.get('microblogs', [])
    if microblogs:
        filtered['microblogs'] = [
            m for m in microblogs
            if not is_default_user(m.get('userUid') or m.get('user', {}).get('uid'))
        ]
        skipped = len(microblogs) - len(filtered['microblogs'])
        if skipped > 0:
            print(f"  Filtered out {skipped} microblogs from default users")

    # Filter posts - exclude those from default users
    posts = all_data.get('posts', [])
    if posts:
        filtered['posts'] = [
            p for p in posts
            if not is_default_user(p.get('userUid') or p.get('user', {}).get('uid') if isinstance(p.get('user'), dict) else None)
        ]
        skipped = len(posts) - len(filtered['posts'])
        if skipped > 0:
            print(f"  Filtered out {skipped} posts from default users")

    # Copy all new data types (classrooms, feedback, study, personas, user_personas)
    # These don't have default data to filter
    for key in ['classrooms', 'feedback', 'study', 'personas', 'user_personas']:
        if key in all_data:
            filtered[key] = all_data[key]

    # Copy any other data types (like _metadata)
    for key in all_data:
        if key not in filtered:
            filtered[key] = all_data[key]

    return filtered


def load_sections(sections_data):
    """Load sections into the database."""
    from model.user import Section

    loaded = 0
    for section_data in sections_data:
        try:
            # Check if section already exists
            existing = Section.query.filter_by(_abbreviation=section_data.get('abbreviation')).first()
            if existing:
                print(f"  Section '{section_data.get('abbreviation')}' already exists, skipping.")
                continue

            section = Section(
                name=section_data.get('name'),
                abbreviation=section_data.get('abbreviation')
            )
            section.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading section {section_data.get('abbreviation')}: {e}")

    print(f"  Loaded {loaded} sections.")


def load_users(users_data):
    """Load users into the database."""
    from model.user import User, Section

    loaded = 0
    skipped = 0
    for user_data in users_data:
        try:
            uid = user_data.get('uid')

            # Check if user already exists
            existing = User.query.filter_by(_uid=uid).first()
            if existing:
                skipped += 1
                continue

            # Create user (note: email is not a constructor param, set via property after)
            user = User(
                name=user_data.get('name'),
                uid=uid,
                password=user_data.get('password', ''),
                sid=user_data.get('sid'),
                role=user_data.get('role', 'User'),
                pfp=user_data.get('pfp'),
                kasm_server_needed=user_data.get('kasm_server_needed', False),
                grade_data=user_data.get('grade_data') or user_data.get('gradeData'),
                ap_exam=user_data.get('ap_exam') or user_data.get('apExam'),
                school=user_data.get('school'),
                classes=user_data.get('class') or user_data.get('_class')
            )

            # Set email via property (not a constructor param)
            if user_data.get('email'):
                user.email = user_data.get('email')

            # Add sections if provided
            sections = user_data.get('sections', [])
            for section_data in sections:
                section_abbrev = section_data.get('abbreviation')
                if section_abbrev:
                    section = Section.query.filter_by(_abbreviation=section_abbrev).first()
                    if section:
                        user.sections.append(section)

            user.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading user {user_data.get('uid')}: {e}")

    if skipped > 0:
        print(f"  Skipped {skipped} users (already exist)")
    print(f"  Loaded {loaded} users.")


def load_topics(topics_data):
    """Load microblog topics into the database."""
    from model.microblog import Topic
    
    loaded = 0
    for topic_data in topics_data:
        try:
            # Handle both camelCase (API) and snake_case (DB) field names
            page_path = topic_data.get('pagePath') or topic_data.get('page_path')
            
            if not page_path:
                print(f"  Skipping topic - no page_path")
                continue
            
            # Check if topic already exists
            existing = Topic.query.filter_by(_page_path=page_path).first()
            if existing:
                print(f"  Topic '{page_path}' already exists, skipping.")
                continue
            
            topic = Topic(
                page_path=page_path,
                page_title=topic_data.get('pageTitle') or topic_data.get('page_title'),
                page_description=topic_data.get('pageDescription') or topic_data.get('page_description'),
                display_name=topic_data.get('displayName') or topic_data.get('display_name'),
                color=topic_data.get('color', '#007bff'),
                icon=topic_data.get('icon'),
                allow_anonymous=topic_data.get('allowAnonymous') or topic_data.get('allow_anonymous', False),
                moderated=topic_data.get('moderated', False),
                max_posts_per_user=topic_data.get('maxPostsPerUser') or topic_data.get('max_posts_per_user', 10),
                settings=topic_data.get('settings', {})
            )
            topic.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading topic: {e}")
    
    print(f"  Loaded {loaded} topics.")


def load_microblogs(microblogs_data, user_uid_map=None):
    """Load microblogs into the database.
    
    Args:
        microblogs_data: List of microblog data from API
        user_uid_map: Optional dict mapping old user_id -> uid for lookup
    """
    from model.microblog import MicroBlog, Topic
    from model.user import User
    
    loaded = 0
    skipped = 0
    for mb_data in microblogs_data:
        try:
            # Find user by uid (preferred) or by mapping old user_id to uid
            user = None
            user_uid = mb_data.get('userUid') or mb_data.get('user', {}).get('uid')
            old_user_id = mb_data.get('userId') or mb_data.get('user_id')
            
            # First try by uid directly
            if user_uid:
                user = User.query.filter_by(_uid=user_uid).first()
            
            # If not found and we have a mapping, try to look up uid from old user_id
            if not user and old_user_id and user_uid_map:
                mapped_uid = user_uid_map.get(old_user_id)
                if mapped_uid:
                    user = User.query.filter_by(_uid=mapped_uid).first()
            
            if not user:
                skipped += 1
                continue
            
            # Find topic if specified (handle both camelCase and snake_case)
            topic_id = None
            topic_path = mb_data.get('topicPath') or mb_data.get('topicKey') or mb_data.get('topic', {}).get('page_path')
            
            # Look up topic by path (more reliable than old topic_id)
            if topic_path:
                topic = Topic.query.filter_by(_page_path=topic_path).first()
                if topic:
                    topic_id = topic.id
            
            content = mb_data.get('content')
            if not content:
                skipped += 1
                continue
            
            microblog = MicroBlog(
                user_id=user.id,
                content=content,
                topic_id=topic_id,
                data=mb_data.get('data', {})
            )
            microblog.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading microblog: {e}")
            skipped += 1
    
    if skipped > 0:
        print(f"  Skipped {skipped} microblogs (user not found or invalid)")
    print(f"  Loaded {loaded} microblogs.")


def load_posts(posts_data, user_uid_map=None):
    """Load social media posts into the database.
    
    Args:
        posts_data: List of post data from API
        user_uid_map: Optional dict mapping old user_id -> uid for lookup
    """
    from model.post import Post
    from model.user import User
    
    # First pass: create all top-level posts (no parent)
    id_mapping = {}  # old_id -> new_id
    loaded = 0
    skipped = 0
    
    # Separate posts and replies (handle both camelCase and snake_case)
    top_level = [p for p in posts_data if not (p.get('parent_id') or p.get('parentId'))]
    replies = [p for p in posts_data if p.get('parent_id') or p.get('parentId')]
    
    for post_data in top_level:
        try:
            # Find user - Posts API returns userId (int) and studentName (string)
            # We need to map old userId to uid, then look up by uid
            user = None
            old_user_id = post_data.get('userId') or post_data.get('user_id')
            student_name = post_data.get('studentName')
            
            # Try to find user by mapping old_user_id to uid
            if old_user_id and user_uid_map:
                mapped_uid = user_uid_map.get(old_user_id)
                if mapped_uid:
                    user = User.query.filter_by(_uid=mapped_uid).first()
            
            # Fallback: try to find user by name (less reliable but better than nothing)
            if not user and student_name and student_name != 'Unknown':
                user = User.query.filter_by(_name=student_name).first()
            
            if not user:
                skipped += 1
                continue
            
            post = Post(
                user_id=user.id,
                content=post_data.get('content'),
                grade_received=post_data.get('gradeReceived') or post_data.get('grade_received'),
                page_url=post_data.get('pageUrl') or post_data.get('page_url'),
                page_title=post_data.get('pageTitle') or post_data.get('page_title')
            )
            created = post.create()
            if created:
                old_id = post_data.get('id')
                if old_id:
                    id_mapping[old_id] = created.id
                loaded += 1
        except Exception as e:
            print(f"  Error loading post: {e}")
            skipped += 1
    
    # Second pass: create replies
    for reply_data in replies:
        try:
            user = None
            old_user_id = reply_data.get('userId') or reply_data.get('user_id')
            student_name = reply_data.get('studentName')
            
            # Try to find user by mapping
            if old_user_id and user_uid_map:
                mapped_uid = user_uid_map.get(old_user_id)
                if mapped_uid:
                    user = User.query.filter_by(_uid=mapped_uid).first()
            
            # Fallback: try by name
            if not user and student_name and student_name != 'Unknown':
                user = User.query.filter_by(_name=student_name).first()
            
            if not user:
                skipped += 1
                continue
            
            # Map old parent_id to new parent_id
            old_parent_id = reply_data.get('parentId') or reply_data.get('parent_id')
            new_parent_id = id_mapping.get(old_parent_id)
            
            if not new_parent_id:
                skipped += 1
                continue
            
            reply = Post(
                user_id=user.id,
                content=reply_data.get('content'),
                parent_id=new_parent_id
            )
            reply.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading reply: {e}")
            skipped += 1
    
    if skipped > 0:
        print(f"  Skipped {skipped} posts/replies (user not found or invalid parent)")
    print(f"  Loaded {loaded} posts/replies.")


def load_classrooms(classrooms_data, user_uid_map=None):
    """Load classrooms with student associations."""
    from model.classroom import Classroom
    from model.user import User

    loaded = 0
    skipped = 0
    for classroom_data in classrooms_data:
        try:
            # Find owner by uid
            owner_uid = classroom_data.get('ownerUid')
            owner = User.query.filter_by(_uid=owner_uid).first() if owner_uid else None
            if not owner:
                skipped += 1
                continue

            classroom = Classroom(
                name=classroom_data.get('name'),
                school_name=classroom_data.get('school_name') or classroom_data.get('schoolName'),
                owner_teacher_id=owner.id,
                status=classroom_data.get('status', 'active')
            )
            classroom.create()

            # Add students
            student_uids = classroom_data.get('studentUids', [])
            for student_uid in student_uids:
                student = User.query.filter_by(_uid=student_uid).first()
                if student:
                    classroom.students.append(student)

            db.session.commit()
            loaded += 1
        except Exception as e:
            print(f"  Error loading classroom: {e}")
            skipped += 1

    if skipped > 0:
        print(f"  Skipped {skipped} classrooms (owner not found)")
    print(f"  Loaded {loaded} classrooms.")


def load_feedback(feedback_data):
    """Load feedback records."""
    from model.feedback import Feedback

    loaded = 0
    for fb_data in feedback_data:
        try:
            feedback = Feedback(
                title=fb_data.get('title'),
                body=fb_data.get('body'),
                type=fb_data.get('type', 'Other'),
                github_username=fb_data.get('github_username')
            )
            feedback.github_issue_url = fb_data.get('github_issue_url')
            feedback.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading feedback: {e}")

    print(f"  Loaded {loaded} feedback records.")


def load_study(study_data, user_uid_map=None):
    """Load study tracker records."""
    from model.study import Study
    from model.user import User

    loaded = 0
    skipped = 0
    for study_record in study_data:
        try:
            # Find user by uid
            user_uid = study_record.get('userUid')
            user = User.query.filter_by(_uid=user_uid).first() if user_uid else None

            study = Study(
                user_id=user.id if user else None,
                topic=study_record.get('topic'),
                subtopic=study_record.get('subtopic'),
                studied=study_record.get('studied', False),
                timestamp=study_record.get('timestamp')
            )
            study.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading study record: {e}")
            skipped += 1

    if skipped > 0:
        print(f"  Skipped {skipped} study records")
    print(f"  Loaded {loaded} study records.")


def load_personas(personas_data):
    """Load personas."""
    from model.persona import Persona

    loaded = 0
    for persona_data in personas_data:
        try:
            existing = Persona.query.filter_by(_alias=persona_data.get('alias')).first()
            if existing:
                continue

            persona = Persona(
                _alias=persona_data.get('alias'),
                _category=persona_data.get('category'),
                _bio_map=persona_data.get('bio_map') or persona_data.get('bioMap'),
                _empathy_map=persona_data.get('empathy_map') or persona_data.get('empathyMap')
            )
            persona.create()
            loaded += 1
        except Exception as e:
            print(f"  Error loading persona: {e}")

    print(f"  Loaded {loaded} personas.")


def load_user_personas(user_personas_data):
    """Load user-persona associations."""
    from model.persona import Persona, UserPersona
    from model.user import User

    loaded = 0
    skipped = 0
    for up_data in user_personas_data:
        try:
            user_uid = up_data.get('userUid')
            persona_alias = up_data.get('personaAlias')

            user = User.query.filter_by(_uid=user_uid).first() if user_uid else None
            persona = Persona.query.filter_by(_alias=persona_alias).first() if persona_alias else None

            if not user or not persona:
                skipped += 1
                continue

            # Check if already exists
            existing = UserPersona.query.filter_by(user_id=user.id, persona_id=persona.id).first()
            if existing:
                continue

            user_persona = UserPersona(
                user=user,
                persona=persona,
                weight=up_data.get('weight', 1)
            )
            db.session.add(user_persona)
            db.session.commit()
            loaded += 1
        except Exception as e:
            print(f"  Error loading user-persona association: {e}")
            skipped += 1

    if skipped > 0:
        print(f"  Skipped {skipped} user-persona associations")
    print(f"  Loaded {loaded} user-persona associations.")


# Main extraction and loading process
def main():
    
    # Step 0: Warning to the user and backup table
    with app.app_context():
        try:
            # Step 3: Build New schema
            # Check if the database has any tables
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if tables:
                print("Warning, you are about to lose all data in your local sqlite database!")
                print("Do you want to continue? (y/n)")
                response = input()
                if response.lower() != 'y':
                    print("Exiting without making changes.")
                    sys.exit(0)
                    
            # Backup the old database
            backup_database(app.config['SQLALCHEMY_DATABASE_URI'], app.config['SQLALCHEMY_BACKUP_URI'], app.config['SQLALCHEMY_DATABASE_STRING'])  
                 
        except OperationalError as e:
            if "Unknown database" in str(e):
                # Create the database if it does not exist
                engine = create_engine(app.config['SQLALCHEMY_DATABASE_STRING'])
                create_database(engine, app.config['SQLALCHEMY_DATABASE_NAME'])
                # Retry the operation
                with app.app_context():
                    db.create_all()
                    print("All tables created after database creation.")
                    
            else:
                print(f"An error occurred: {e}")
                sys.exit(1) 
                
        except Exception as e:
            print(f"An error occurred: {e}")
            sys.exit(1)
        
    # Step 1: Authenticate to production server
    print("\n=== Step 1: Authenticating to production server ===")
    cookies, error = authenticate(UID, PASSWORD)
    if error:
        print(error)
        print("Using local JSON data as fallback.")
        all_data, error = read_data_from_json(JSON_DATA)
        if error or all_data is None:
            print(f"Error: {error}")
            print("\nCannot proceed: Authentication failed and no local backup data available.")
            print("Please fix the authentication issue or ensure instance/data.json exists.")
            sys.exit(1)
    else:
        # Step 2: Extract ALL data from production
        print("\n=== Step 2: Extracting ALL data from production ===")
        all_data, errors = extract_all_data(cookies)
        if errors:
            print(f"Error extracting data: {errors}")
            print("Falling back to local JSON data if available...")
            all_data, error = read_data_from_json(JSON_DATA)
            if error or all_data is None:
                print(f"Error: {error}")
                print("\nCannot proceed: Export failed and no local backup data available.")
                print("Please fix the server issue or ensure instance/data.json exists.")
                sys.exit(1)
        else:
            # Save all extracted data to JSON for backup
            write_data_to_json(all_data, JSON_DATA)

    print("\n=== Data extraction complete ===")
    if not all_data:
        print("Error: No data was extracted!")
        sys.exit(1)

    # Validate that all_data is a dictionary
    if not isinstance(all_data, dict):
        print(f"Error: Expected dictionary but got {type(all_data).__name__}")
        print("The JSON backup file may be in an incompatible format.")
        sys.exit(1)

    for key, data in all_data.items():
        if data:
            count = len(data) if isinstance(data, list) else 1
            print(f"  {key}: {count} records")
        else:
            print(f"  {key}: No data")
    
    # Filter out default/test data
    print("\n=== Filtering out default/test data ===")
    all_data = filter_default_data(all_data)
    
    print("\n=== Data after filtering ===")
    for key, data in all_data.items():
        if data:
            count = len(data) if isinstance(data, list) else 1
            print(f"  {key}: {count} records")
        else:
            print(f"  {key}: No data")
    
    # Step 3: Build New schema and load data 
    print("\n=== Step 3: Building new schema and loading data ===")
    try:
        with app.app_context():
            # Drop all the tables defined in the project
            db.drop_all()
            print("All tables dropped.")
            
            # Create all tables
            db.create_all()
            print("All tables created.")
            
            # Add default test data 
            initUsers() # test data
            
            # Build user_uid_map from extracted users data
            # This maps old user_id (int) -> uid (string) for lookup after users are loaded
            users_data = all_data.get('users', [])
            user_uid_map = {}
            for user in users_data:
                old_id = user.get('id')
                uid = user.get('uid')
                if old_id and uid:
                    user_uid_map[old_id] = uid
            print(f"\nBuilt user_uid_map with {len(user_uid_map)} entries")
            
            # Load data into the local database in proper order
            # 1. Sections first (users depend on sections)
            sections_data = all_data.get('sections', [])
            if sections_data:
                print(f"\nLoading {len(sections_data)} sections...")
                load_sections(sections_data)

            # 2. Users (includes their section associations)
            if users_data:
                print(f"\nLoading {len(users_data)} users...")
                load_users(users_data)

            # 3. Topics (microblogs depend on topics)
            topics_data = all_data.get('topics', [])
            if topics_data:
                print(f"\nLoading {len(topics_data)} topics...")
                load_topics(topics_data)

            # 4. Microblogs (pass user_uid_map for user lookups)
            microblogs_data = all_data.get('microblogs', [])
            if microblogs_data:
                print(f"\nLoading {len(microblogs_data)} microblogs...")
                load_microblogs(microblogs_data, user_uid_map)

            # 5. Posts (pass user_uid_map for user lookups)
            posts_data = all_data.get('posts', [])
            if posts_data:
                print(f"\nLoading {len(posts_data)} posts...")
                load_posts(posts_data, user_uid_map)

            # 6. Personas (no dependencies)
            personas_data = all_data.get('personas', [])
            if personas_data:
                print(f"\nLoading {len(personas_data)} personas...")
                load_personas(personas_data)

            # 7. User-persona associations (depends on users and personas)
            user_personas_data = all_data.get('user_personas', [])
            if user_personas_data:
                print(f"\nLoading {len(user_personas_data)} user-persona associations...")
                load_user_personas(user_personas_data)

            # 8. Classrooms (depends on users)
            classrooms_data = all_data.get('classrooms', [])
            if classrooms_data:
                print(f"\nLoading {len(classrooms_data)} classrooms...")
                load_classrooms(classrooms_data, user_uid_map)

            # 9. Feedback (no critical dependencies)
            feedback_data = all_data.get('feedback', [])
            if feedback_data:
                print(f"\nLoading {len(feedback_data)} feedback records...")
                load_feedback(feedback_data)

            # 10. Study tracker (depends on users)
            study_data = all_data.get('study', [])
            if study_data:
                print(f"\nLoading {len(study_data)} study records...")
                load_study(study_data, user_uid_map)


    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Log success 
    print("\n=== Database initialized successfully! ===")
 
if __name__ == "__main__":
    main()