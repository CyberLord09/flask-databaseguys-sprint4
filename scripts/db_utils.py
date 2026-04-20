#!/usr/bin/env python3

"""
db_utils.py
Shared utilities for database migration scripts.

Responsibilities:
- Shared configuration (BASE_URL, default data exclusion lists)
- Authentication against the production server
- Filtering default/seed data that should not be migrated
"""

import os
import sys
import requests

# Add the root directory to sys.path so app imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from main import app

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = "https://flask.opencodingsociety.com"
AUTH_URL  = f"{BASE_URL}/api/authenticate"

# Credentials loaded from app config
UID      = app.config['ADMIN_UID']
PASSWORD = app.config['ADMIN_PASSWORD']

# Default data created by initUsers / init_posts that must not be duplicated
DEFAULT_DATA = {
    'users': [
        app.config.get('ADMIN_UID', 'admin'),
        app.config.get('DEFAULT_UID', 'user'),
        'niko',
    ],
    'sections': ['CSA', 'CSP', 'Robotics', 'CSSE'],
    'topics': [
        '/lessons/flask-introduction',
        '/hacks/javascript-basics',
        '/projects/portfolio-showcase',
        '/general/daily-standup',
        '/resources/study-materials',
    ],
}

# ── Authentication ─────────────────────────────────────────────────────────────

def authenticate(uid=None, password=None):
    """Authenticate against the production server and return (cookies, error)."""
    uid      = uid      or UID
    password = password or PASSWORD

    auth_data = {"uid": uid, "password": password}
    headers   = {"Content-Type": "application/json", "X-Origin": "client"}

    print(f"  Authenticating as: {uid}")
    try:
        response = requests.post(AUTH_URL, json=auth_data, headers=headers)
        response.raise_for_status()
        print("  ✓ Authentication successful")
        return response.cookies, None
    except requests.RequestException as e:
        return None, {
            'message': 'Failed to authenticate',
            'code':    getattr(response, 'status_code', 0),
            'error':   str(e),
        }

# ── Default-data filters ───────────────────────────────────────────────────────

def is_default_user(uid):
    return uid in DEFAULT_DATA['users']

def is_default_section(abbreviation):
    return abbreviation in DEFAULT_DATA['sections']

def is_default_topic(page_path):
    return page_path in DEFAULT_DATA['topics']


def filter_default_data(all_data):
    """Remove seed/default records from *all_data* and return the cleaned copy."""
    filtered = {}

    users = all_data.get('users', [])
    if users:
        filtered['users'] = [u for u in users if not is_default_user(u.get('uid'))]
        skipped = len(users) - len(filtered['users'])
        if skipped:
            print(f"  Filtered out {skipped} default users")

    sections = all_data.get('sections', [])
    if sections:
        filtered['sections'] = [s for s in sections if not is_default_section(s.get('abbreviation'))]
        skipped = len(sections) - len(filtered['sections'])
        if skipped:
            print(f"  Filtered out {skipped} default sections")

    topics = all_data.get('topics', [])
    if topics:
        page_path_key = 'pagePath' if 'pagePath' in topics[0] else 'page_path'
        filtered['topics'] = [
            t for t in topics
            if not is_default_topic(t.get(page_path_key) or t.get('page_path'))
        ]
        skipped = len(topics) - len(filtered['topics'])
        if skipped:
            print(f"  Filtered out {skipped} default topics")

    microblogs = all_data.get('microblogs', [])
    if microblogs:
        filtered['microblogs'] = [
            m for m in microblogs
            if not is_default_user(m.get('userUid') or m.get('user', {}).get('uid'))
        ]
        skipped = len(microblogs) - len(filtered['microblogs'])
        if skipped:
            print(f"  Filtered out {skipped} microblogs from default users")

    posts = all_data.get('posts', [])
    if posts:
        filtered['posts'] = [
            p for p in posts
            if not is_default_user(
                p.get('userUid') or
                (p.get('user', {}).get('uid') if isinstance(p.get('user'), dict) else None)
            )
        ]
        skipped = len(posts) - len(filtered['posts'])
        if skipped:
            print(f"  Filtered out {skipped} posts from default users")

    # Pass-through for types without default data
    for key in all_data:
        if key not in filtered:
            filtered[key] = all_data[key]

    return filtered
