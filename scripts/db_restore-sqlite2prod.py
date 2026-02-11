#!/usr/bin/env python3

"""
db_restore-sqlite2prod.py
Restores ALL data from local SQLite database to production database via API endpoints.

This script reads directly from the active database (instance/volumes/user_management.db)
and uploads all data types:
- Sections
- Users (with section associations)
- Topics (microblog categories)
- Microblogs
- Posts
- Classrooms
- Feedback
- Study tracker records
- Personas
- User-Persona associations

If database reading fails, it falls back to instance/data.json.

Usage: Run from the terminal as such:
> ./scripts/db_restore-sqlite2prod.py

Or run from the root of the project:
> python scripts/db_restore-sqlite2prod.py
"""

import requests
import json
import os
import sys

# Add the directory containing main.py to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import app BEFORE using app.config
from main import app, db

# Configuration
BASE_URL = "https://flask.opencodingsociety.com"
PROD_AUTH_URL = f"{BASE_URL}/api/authenticate"
LOCAL_JSON = "instance/data.json"

# API Endpoints for chunked data import (one per data type)
# Order matters: sections and users must be imported first as other data depends on them
IMPORT_ENDPOINTS = {
    'sections': '/api/export/import/sections',
    'users': '/api/export/import/users',
    'topics': '/api/export/import/topics',
    'microblogs': '/api/export/import/microblogs',
    'posts': '/api/export/import/posts',
    'classrooms': '/api/export/import/classrooms',
    'feedback': '/api/export/import/feedback',
    'study': '/api/export/import/study',
    'personas': '/api/export/import/personas',
    'user_personas': '/api/export/import/user_personas',
}

# Hardcoded credentials for production authentication
UID = app.config['ADMIN_UID']
PASSWORD = app.config['ADMIN_PASSWORD']

# Default data to EXCLUDE from restore (created by initUsers, init_posts, etc.)
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
}


def authenticate(uid, password):
    """Authenticate to production server and return session cookies."""
    auth_data = {"uid": uid, "password": password}
    headers = {
        "Content-Type": "application/json",
        "X-Origin": "client"
    }
    
    print(f"  Authenticating as: {uid}")
    
    try:
        response = requests.post(PROD_AUTH_URL, json=auth_data, headers=headers)
        response.raise_for_status()
        print(f"  ✓ Authentication successful")
        return response.cookies, None
    except requests.RequestException as e:
        return None, {
            'message': 'Failed to authenticate',
            'code': getattr(response, 'status_code', 0),
            'error': str(e)
        }


def read_local_data_from_db():
    """Read ALL data from the local SQLite database."""
    try:
        from main import app, db
        from model.user import User, Section
        from model.post import Post
        from model.microblog import MicroBlog, Topic
        from model.classroom import Classroom
        from model.feedback import Feedback
        from model.study import Study
        from model.persona import Persona, UserPersona

        with app.app_context():
            print("  Reading ALL data from local database...")

            all_data = {}

            # 1. Export sections
            sections = Section.query.all()
            all_data['sections'] = [s.read() for s in sections]
            print(f"    Found {len(all_data['sections'])} sections")

            # 2. Export users with their sections
            users = User.query.all()
            all_data['users'] = []
            for user in users:
                user_data = user.read()
                user_data['sections'] = [s.read() for s in user.sections]
                all_data['users'].append(user_data)
            print(f"    Found {len(all_data['users'])} users")

            # 3. Export topics
            topics = Topic.query.all()
            all_data['topics'] = [t.read() for t in topics]
            print(f"    Found {len(all_data['topics'])} topics")

            # 4. Export microblogs
            microblogs = MicroBlog.query.all()
            all_data['microblogs'] = []
            for mb in microblogs:
                mb_data = mb.read()
                if mb.user:
                    mb_data['userUid'] = mb.user.uid
                if mb.topic:
                    mb_data['topicPath'] = mb.topic._page_path
                all_data['microblogs'].append(mb_data)
            print(f"    Found {len(all_data['microblogs'])} microblogs")

            # 5. Export posts
            posts = Post.query.all()
            all_data['posts'] = []
            for post in posts:
                post_data = post.read()
                if post.user:
                    post_data['userUid'] = post.user.uid
                all_data['posts'].append(post_data)
            print(f"    Found {len(all_data['posts'])} posts")

            # 6. Export classrooms
            classrooms = Classroom.query.all()
            all_data['classrooms'] = []
            for classroom in classrooms:
                classroom_data = classroom.to_dict()
                owner = User.query.get(classroom.owner_teacher_id)
                if owner:
                    classroom_data['ownerUid'] = owner.uid
                classroom_data['studentUids'] = [s.uid for s in classroom.students.all()]
                all_data['classrooms'].append(classroom_data)
            print(f"    Found {len(all_data['classrooms'])} classrooms")

            # 7. Export feedback
            feedback_items = Feedback.query.all()
            all_data['feedback'] = [f.read() for f in feedback_items]
            print(f"    Found {len(all_data['feedback'])} feedback records")

            # 8. Export study
            study_records = Study.query.all()
            all_data['study'] = []
            for study in study_records:
                study_data = study.to_dict()
                if study.user_id:
                    user = User.query.get(study.user_id)
                    if user:
                        study_data['userUid'] = user.uid
                all_data['study'].append(study_data)
            print(f"    Found {len(all_data['study'])} study records")

            # 9. Export personas
            personas = Persona.query.all()
            all_data['personas'] = [p.read() for p in personas]
            print(f"    Found {len(all_data['personas'])} personas")

            # 10. Export user_personas
            user_personas = UserPersona.query.all()
            all_data['user_personas'] = []
            for up in user_personas:
                all_data['user_personas'].append({
                    'userUid': up.user.uid if up.user else None,
                    'personaAlias': up.persona.alias if up.persona else None,
                    'weight': up.weight,
                    'selectedAt': up.selected_at.isoformat() if up.selected_at else None
                })
            print(f"    Found {len(all_data['user_personas'])} user-persona associations")

            return all_data, None

    except Exception as e:
        return None, {'message': f'Failed to read from database: {str(e)}'}


def read_local_data(json_file):
    """Read data from local JSON file (legacy fallback)."""
    if not os.path.exists(json_file):
        return None, {'message': f'JSON file not found: {json_file}'}

    with open(json_file, "r") as f:
        data = json.load(f)

    # Handle both old format (list of users) and new format (dict with multiple data types)
    if isinstance(data, list):
        # Old format: just a list of users
        return {'users': data}, None
    elif isinstance(data, dict):
        # New format: dict with multiple data types
        return data, None
    else:
        return None, {'message': 'Unknown data format in JSON file'}


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
            if not is_default_user(p.get('user', {}).get('uid') if isinstance(p.get('user'), dict) else None)
        ]
        skipped = len(posts) - len(filtered['posts'])
        if skipped > 0:
            print(f"  Filtered out {skipped} posts from default users")
    
    # Copy any other data types unchanged
    for key in all_data:
        if key not in filtered:
            filtered[key] = all_data[key]
    
    return filtered


def import_all_data(all_data, cookies):
    """
    Import all data to production using chunked endpoints (one per data type).
    For large datasets (users), breaks into smaller batches to avoid timeout.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Origin": "client"
    }

    print("  Using chunked import endpoints (one per data type)...")

    results = {}
    total_imported = 0
    total_failed = 0
    failed_endpoints = []

    for data_type, endpoint in IMPORT_ENDPOINTS.items():
        # Get data for this type
        data_list = all_data.get(data_type, [])

        # Skip if no data for this type
        if not data_list:
            print(f"  Skipping {data_type}: no data")
            continue

        url = BASE_URL + endpoint

        # For large datasets, use batching to avoid timeout
        # Batch size of 50 matches the pagination size for consistency
        large_datasets = ['users', 'microblogs', 'posts', 'user_personas', 'personas']
        batch_size = 50 if data_type in large_datasets else None

        if batch_size and len(data_list) > batch_size:
            # Upload in batches
            print(f"  Uploading {data_type} ({len(data_list)} records in batches of {batch_size})...")

            combined_stats = {'imported': 0, 'failed': 0, 'errors': []}
            batches = [data_list[i:i+batch_size] for i in range(0, len(data_list), batch_size)]

            for i, batch in enumerate(batches, 1):
                print(f"    Batch {i}/{len(batches)} ({len(batch)} records)...", end=" ", flush=True)

                try:
                    payload = {data_type: batch}
                    response = requests.post(url, json=payload, headers=headers, cookies=cookies, timeout=180)

                    if response.status_code in [200, 201]:
                        result = response.json()
                        stats = result.get(data_type, {})
                        combined_stats['imported'] += stats.get('imported', 0)
                        combined_stats['failed'] += stats.get('failed', 0)
                        combined_stats['errors'].extend(stats.get('errors', []))

                        status = "✓" if stats.get('failed', 0) == 0 else "⚠"
                        print(f"{status} {stats.get('imported', 0)} imported, {stats.get('failed', 0)} failed")
                    else:
                        print(f"✗ Error {response.status_code}")
                        combined_stats['failed'] += len(batch)
                        combined_stats['errors'].append(f"Batch {i} HTTP {response.status_code}")

                except requests.Timeout:
                    print(f"✗ Timeout")
                    combined_stats['failed'] += len(batch)
                    combined_stats['errors'].append(f"Batch {i} timeout")
                except requests.RequestException as e:
                    print(f"✗ Error: {str(e)[:50]}")
                    combined_stats['failed'] += len(batch)
                    combined_stats['errors'].append(f"Batch {i}: {str(e)[:50]}")

            results[data_type] = combined_stats
            total_imported += combined_stats['imported']
            total_failed += combined_stats['failed']

            # Show summary
            print(f"    Total: {combined_stats['imported']} imported, {combined_stats['failed']} failed")
            if combined_stats['errors'][:3]:
                for error in combined_stats['errors'][:3]:
                    print(f"      - {error}")
                if len(combined_stats['errors']) > 3:
                    print(f"      ... and {len(combined_stats['errors']) - 3} more errors")

        else:
            # Regular single-request upload
            print(f"  Uploading {data_type} ({len(data_list)} records)...", end=" ", flush=True)

            try:
                # Send data wrapped in the expected key
                payload = {data_type: data_list}
                response = requests.post(url, json=payload, headers=headers, cookies=cookies, timeout=180)

                if response.status_code in [200, 201]:
                    result = response.json()

                    # Extract stats from response
                    stats = result.get(data_type, {})
                    imported = stats.get('imported', 0)
                    failed = stats.get('failed', 0)
                    errors = stats.get('errors', [])

                    results[data_type] = stats
                    total_imported += imported
                    total_failed += failed

                    status = "✓" if failed == 0 else "⚠"
                    print(f"{status} {imported} imported, {failed} failed")

                    # Show first few errors if any
                    if errors:
                        for error in errors[:3]:
                            print(f"      - {error}")
                        if len(errors) > 3:
                            print(f"      ... and {len(errors) - 3} more errors")
                else:
                    print(f"✗ Error {response.status_code}")
                    failed_endpoints.append((data_type, f"Status {response.status_code}"))
                    results[data_type] = {'imported': 0, 'failed': len(data_list), 'errors': [f"HTTP {response.status_code}"]}
                    total_failed += len(data_list)

            except requests.Timeout:
                print(f"✗ Timeout")
                failed_endpoints.append((data_type, "Request timeout"))
                results[data_type] = {'imported': 0, 'failed': len(data_list), 'errors': ["Timeout"]}
                total_failed += len(data_list)
            except requests.RequestException as e:
                print(f"✗ Error: {e}")
                failed_endpoints.append((data_type, str(e)))
                results[data_type] = {'imported': 0, 'failed': len(data_list), 'errors': [str(e)]}
                total_failed += len(data_list)

    print(f"\n  Total: {total_imported} imported, {total_failed} failed")

    if failed_endpoints:
        print(f"\n  WARNING: {len(failed_endpoints)} endpoint(s) had issues:")
        for data_type, error in failed_endpoints:
            print(f"    - {data_type}: {error}")
        return False, {'results': results, 'failed_endpoints': failed_endpoints}

    return True, {'results': results}


def main():
    print("=" * 60)
    print("Database Restore: SQLite → Production")
    print("=" * 60)
    
    # Step 1: Authenticate to production server
    print("\n=== Step 1: Authenticating to production server ===")
    cookies, error = authenticate(UID, PASSWORD)
    if error:
        print(f"  ✗ Authentication failed: {error}")
        print("\nPlease check your credentials in app config or environment variables.")
        return 1
    
    # Step 2: Read local data from the active database
    print("\n=== Step 2: Reading local data from database ===")
    all_data, error = read_local_data_from_db()
    if error:
        print(f"  ✗ Failed to read from database: {error}")
        print("  Trying to read from JSON backup instead...")
        all_data, error = read_local_data(LOCAL_JSON)
        if error:
            print(f"  ✗ Failed to read local data: {error}")
            return 1
    
    # Show what we have before filtering
    print(f"  Found data types (before filtering):")
    for key, data in all_data.items():
        if data:
            count = len(data) if isinstance(data, list) else 1
            print(f"    - {key}: {count} records")
    
    # Filter out default/test data
    print("\n=== Filtering out default/test data ===")
    all_data = filter_default_data(all_data)
    
    # Show what we have after filtering
    print(f"\n  Data to upload (after filtering):")
    for key, data in all_data.items():
        if data:
            count = len(data) if isinstance(data, list) else 1
            print(f"    - {key}: {count} records")
    
    # Confirm before proceeding
    print("\n⚠️  WARNING: This will upload data to production!")
    print("Do you want to continue? (y/n)")
    response = input().strip().lower()
    if response != 'y':
        print("Aborted.")
        return 0

    # Step 3: Upload ALL data using chunked import endpoints
    print("\n=== Step 3: Uploading data to production (chunked) ===")

    success, result = import_all_data(all_data, cookies)

    if success:
        print("\n" + "=" * 60)
        print("✓ Data upload complete!")
        if 'results' in result:
            print("\n=== Import Summary ===")
            for data_type, stats in result['results'].items():
                imported = stats.get('imported', 0)
                failed = stats.get('failed', 0)
                status = "✓" if failed == 0 else "⚠"
                print(f"  {status} {data_type}: {imported} imported, {failed} failed")
        print("=" * 60)
        return 0
    else:
        print("\n" + "=" * 60)
        print("✗ Data upload had failures!")
        if 'results' in result:
            print("\n=== Import Summary ===")
            for data_type, stats in result['results'].items():
                imported = stats.get('imported', 0)
                failed = stats.get('failed', 0)
                status = "✓" if failed == 0 else "✗"
                print(f"  {status} {data_type}: {imported} imported, {failed} failed")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
