#!/usr/bin/env python3

"""
db_restore-sqlite2prod.py
Restores ALL data from the local SQLite database to the production database
via API endpoints.

Responsibility: read local data → filter defaults → upload to production.

Data types uploaded (in dependency order):
  Sections, Users, Topics, Microblogs, Posts, Classrooms,
  Feedback, Study, Personas, User-Persona associations.

Falls back to instance/data.json if the local database cannot be read.

Usage:
  python scripts/db_restore-sqlite2prod.py
  ./scripts/db_restore-sqlite2prod.py
"""

import json
import os
import sys

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app, db
from db_utils import authenticate, filter_default_data, BASE_URL, UID, PASSWORD

# ── Configuration ──────────────────────────────────────────────────────────────

LOCAL_JSON = "instance/data.json"

# Import endpoints (order matters: sections and users first)
IMPORT_ENDPOINTS = {
    'sections':     '/api/export/import/sections',
    'users':        '/api/export/import/users',
    'topics':       '/api/export/import/topics',
    'microblogs':   '/api/export/import/microblogs',
    'posts':        '/api/export/import/posts',
    'classrooms':   '/api/export/import/classrooms',
    'feedback':     '/api/export/import/feedback',
    'study':        '/api/export/import/study',
    'personas':     '/api/export/import/personas',
    'user_personas':'/api/export/import/user_personas',
}

# Data types large enough to need batched uploads
LARGE_DATA_TYPES = {'users', 'microblogs', 'posts', 'user_personas', 'personas'}
BATCH_SIZE = 50

# ── Local data readers ─────────────────────────────────────────────────────────

def read_local_data_from_db():
    """Read all data from the local SQLite database and return (data, error)."""
    try:
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

            sections = Section.query.all()
            all_data['sections'] = [s.read() for s in sections]
            print(f"    Found {len(all_data['sections'])} sections")

            users = User.query.all()
            all_data['users'] = []
            for user in users:
                user_data = user.read()
                user_data['sections'] = [s.read() for s in user.sections]
                all_data['users'].append(user_data)
            print(f"    Found {len(all_data['users'])} users")

            topics = Topic.query.all()
            all_data['topics'] = [t.read() for t in topics]
            print(f"    Found {len(all_data['topics'])} topics")

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

            posts = Post.query.all()
            all_data['posts'] = []
            for post in posts:
                post_data = post.read()
                if post.user:
                    post_data['userUid'] = post.user.uid
                all_data['posts'].append(post_data)
            print(f"    Found {len(all_data['posts'])} posts")

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

            feedback_items = Feedback.query.all()
            all_data['feedback'] = [f.read() for f in feedback_items]
            print(f"    Found {len(all_data['feedback'])} feedback records")

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

            personas = Persona.query.all()
            all_data['personas'] = [p.read() for p in personas]
            print(f"    Found {len(all_data['personas'])} personas")

            user_personas = UserPersona.query.all()
            all_data['user_personas'] = []
            for up in user_personas:
                all_data['user_personas'].append({
                    'userUid':      up.user.uid    if up.user    else None,
                    'personaAlias': up.persona.alias if up.persona else None,
                    'weight':       up.weight,
                    'selectedAt':   up.selected_at.isoformat() if up.selected_at else None,
                })
            print(f"    Found {len(all_data['user_personas'])} user-persona associations")

            return all_data, None

    except Exception as e:
        return None, {'message': f'Failed to read from database: {str(e)}'}


def read_local_data_from_json(json_file):
    """Read data from the JSON fallback file and return (data, error)."""
    if not os.path.exists(json_file):
        return None, {'message': f'JSON file not found: {json_file}'}

    with open(json_file, 'r') as f:
        data = json.load(f)

    if isinstance(data, list):
        return {'users': data}, None
    if isinstance(data, dict):
        return data, None
    return None, {'message': 'Unknown data format in JSON file'}

# ── Production uploader ────────────────────────────────────────────────────────

def _upload_batch(url, data_type, batch, headers, cookies):
    """POST a single batch; return (imported, failed, errors)."""
    try:
        response = requests.post(
            url,
            json={data_type: batch},
            headers=headers,
            cookies=cookies,
            timeout=180,
        )
        if response.status_code in [200, 201]:
            stats = response.json().get(data_type, {})
            return stats.get('imported', 0), stats.get('failed', 0), stats.get('errors', [])
        return 0, len(batch), [f"HTTP {response.status_code}"]
    except requests.Timeout:
        return 0, len(batch), ["Timeout"]
    except requests.RequestException as e:
        return 0, len(batch), [str(e)]


def import_all_data(all_data, cookies):
    """Upload all data to production, batching large datasets.

    Returns (success, result_dict).
    """
    headers = {"Content-Type": "application/json", "X-Origin": "client"}
    results = {}
    total_imported = total_failed = 0
    failed_endpoints = []

    for data_type, endpoint in IMPORT_ENDPOINTS.items():
        data_list = all_data.get(data_type, [])
        if not data_list:
            print(f"  Skipping {data_type}: no data")
            continue

        url = BASE_URL + endpoint
        use_batching = data_type in LARGE_DATA_TYPES and len(data_list) > BATCH_SIZE

        if use_batching:
            batches = [data_list[i:i + BATCH_SIZE] for i in range(0, len(data_list), BATCH_SIZE)]
            print(f"  Uploading {data_type} ({len(data_list)} records in batches of {BATCH_SIZE})...")
            combined = {'imported': 0, 'failed': 0, 'errors': []}

            for i, batch in enumerate(batches, 1):
                print(f"    Batch {i}/{len(batches)} ({len(batch)} records)...", end=" ", flush=True)
                imp, fail, errs = _upload_batch(url, data_type, batch, headers, cookies)
                combined['imported'] += imp
                combined['failed']   += fail
                combined['errors'].extend(errs)
                status = "✓" if fail == 0 else "⚠"
                print(f"{status} {imp} imported, {fail} failed")

            results[data_type] = combined
            total_imported += combined['imported']
            total_failed   += combined['failed']
            print(f"    Total: {combined['imported']} imported, {combined['failed']} failed")
            for err in combined['errors'][:3]:
                print(f"      - {err}")
            if len(combined['errors']) > 3:
                print(f"      ... and {len(combined['errors']) - 3} more errors")

        else:
            print(f"  Uploading {data_type} ({len(data_list)} records)...", end=" ", flush=True)
            imp, fail, errs = _upload_batch(url, data_type, data_list, headers, cookies)
            results[data_type] = {'imported': imp, 'failed': fail, 'errors': errs}
            total_imported += imp
            total_failed   += fail
            status = "✓" if fail == 0 else "⚠"
            print(f"{status} {imp} imported, {fail} failed")
            for err in errs[:3]:
                print(f"      - {err}")
            if len(errs) > 3:
                print(f"      ... and {len(errs) - 3} more errors")
            if fail > 0:
                failed_endpoints.append((data_type, errs[0] if errs else "unknown"))

    print(f"\n  Total: {total_imported} imported, {total_failed} failed")

    if failed_endpoints:
        print(f"\n  WARNING: {len(failed_endpoints)} endpoint(s) had issues:")
        for dt, err in failed_endpoints:
            print(f"    - {dt}: {err}")
        return False, {'results': results, 'failed_endpoints': failed_endpoints}

    return True, {'results': results}

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Database Restore: SQLite → Production")
    print("=" * 60)

    print("\n=== Step 1: Authenticating to production server ===")
    cookies, error = authenticate(UID, PASSWORD)
    if error:
        print(f"  ✗ Authentication failed: {error}")
        print("\nPlease check your credentials in app config or environment variables.")
        return 1

    print("\n=== Step 2: Reading local data from database ===")
    all_data, error = read_local_data_from_db()
    if error:
        print(f"  ✗ Failed to read from database: {error}")
        print("  Trying to read from JSON backup instead...")
        all_data, error = read_local_data_from_json(LOCAL_JSON)
        if error:
            print(f"  ✗ Failed to read local data: {error}")
            return 1

    print("  Found data types (before filtering):")
    for key, data in all_data.items():
        if data:
            print(f"    - {key}: {len(data) if isinstance(data, list) else 1} records")

    print("\n=== Filtering out default/test data ===")
    all_data = filter_default_data(all_data)

    print("\n  Data to upload (after filtering):")
    for key, data in all_data.items():
        if data:
            print(f"    - {key}: {len(data) if isinstance(data, list) else 1} records")

    print("\n⚠️  WARNING: This will upload data to production!")
    print("Do you want to continue? (y/n)")
    if input().strip().lower() != 'y':
        print("Aborted.")
        return 0

    print("\n=== Step 3: Uploading data to production (chunked) ===")
    success, result = import_all_data(all_data, cookies)

    print("\n" + "=" * 60)
    status_icon = "✓" if success else "✗"
    print(f"{status_icon} Data upload {'complete' if success else 'had failures'}!")

    if 'results' in result:
        print("\n=== Import Summary ===")
        for data_type, stats in result['results'].items():
            imp  = stats.get('imported', 0)
            fail = stats.get('failed', 0)
            icon = "✓" if fail == 0 else "✗"
            print(f"  {icon} {data_type}: {imp} imported, {fail} failed")

    print("=" * 60)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
