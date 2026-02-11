"""
=============================================================================
GROQ AI API - General Purpose Endpoints
=============================================================================
Groq is a FREE and FAST AI inference API that uses LLaMA models.

SETUP REQUIRED:
1. Get a free API key from: https://console.groq.com/keys
2. Add to your .env file:
   GROQ_API_KEY=your_key_here
   GROQ_SERVER=https://api.groq.com/openai/v1/chat/completions

ENDPOINTS PROVIDED:
- POST /api/groq              - General chat completions (original endpoint)
- POST /api/groq/chat         - Chat completions with more options
- POST /api/groq/analyze      - Text analysis (summarize, sentiment, keywords)
- GET  /api/groq/models       - List available models
- GET  /api/groq/health       - Health check

MODELS AVAILABLE:
- llama-3.3-70b-versatile     - Best for complex tasks (recommended)
- llama-3.1-8b-instant        - Fast responses, simpler tasks
- llama3-8b-8192              - Legacy model, still works
- mixtral-8x7b-32768          - Good balance of speed and quality

USAGE EXAMPLE (JavaScript frontend):
    fetch('/api/groq/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
            messages: [
                { role: 'system', content: 'You are a helpful assistant.' },
                { role: 'user', content: 'Hello!' }
            ],
            model: 'llama-3.3-70b-versatile'
        })
    })
=============================================================================
"""

from __init__ import app
from flask import Blueprint, request, jsonify, current_app
from flask_restful import Api, Resource
import requests
import os

# Blueprint setup - keeps original name for backwards compatibility
groq_api = Blueprint('groq_api', __name__, url_prefix='/api')
api = Api(groq_api)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MODEL = "llama-3.3-70b-versatile"

AVAILABLE_MODELS = [
    {
        "id": "llama-3.3-70b-versatile",
        "description": "Best for complex reasoning and detailed responses",
        "context_window": 128000,
        "recommended": True
    },
    {
        "id": "llama-3.1-8b-instant",
        "description": "Fast responses for simpler tasks",
        "context_window": 128000,
        "recommended": False
    },
    {
        "id": "llama3-8b-8192",
        "description": "Legacy model, still supported",
        "context_window": 8192,
        "recommended": False
    },
    {
        "id": "mixtral-8x7b-32768",
        "description": "Good balance of speed and quality",
        "context_window": 32768,
        "recommended": False
    }
]


def get_groq_server():
    """Get Groq server URL from app config"""
    return app.config.get('GROQ_SERVER')


def get_groq_api_key():
    """Get Groq API key from app config or environment"""
    return current_app.config.get('GROQ_API_KEY') or os.getenv('GROQ_API_KEY')


# =============================================================================
# ENDPOINTS
# =============================================================================

class GroqAPI:

    class _Generate(Resource):
        """
        Original endpoint - POST /api/groq
        Kept for backwards compatibility.
        """
        def post(self):
            body = request.get_json()
            messages = body.get('messages')

            if not messages:
                return {'message': 'Missing "messages" in request body'}, 400

            api_key = get_groq_api_key()
            if not api_key:
                return {'message': 'GROQ_API_KEY not configured. Add it to .env file.'}, 500

            try:
                response = requests.post(
                    get_groq_server(),
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        "model": body.get('model', DEFAULT_MODEL),
                        "messages": messages,
                        "temperature": body.get('temperature', 0.7)
                    },
                    timeout=60
                )
                response.raise_for_status()
                return response.json(), 200
            except requests.Timeout:
                return {'message': 'Request timed out'}, 504
            except Exception as e:
                return {'message': f'Error contacting Groq API: {str(e)}'}, 500

    class _Chat(Resource):
        """
        Enhanced chat endpoint - POST /api/groq/chat
        More options and better response format.
        """
        def post(self):
            try:
                api_key = get_groq_api_key()
                if not api_key:
                    return {
                        'success': False,
                        'error': 'GROQ_API_KEY not configured. Add it to .env file.'
                    }, 500

                data = request.get_json() or {}
                messages = data.get('messages', [])

                if not messages:
                    return {
                        'success': False,
                        'error': 'messages array is required'
                    }, 400

                model = data.get('model', DEFAULT_MODEL)
                temperature = data.get('temperature', 0.7)
                max_tokens = data.get('max_tokens', 1024)

                response = requests.post(
                    get_groq_server(),
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    },
                    timeout=60
                )

                if response.status_code == 200:
                    api_data = response.json()
                    return {
                        'success': True,
                        'response': api_data['choices'][0]['message']['content'],
                        'model': model,
                        'usage': api_data.get('usage', {})
                    }, 200
                else:
                    return {
                        'success': False,
                        'error': f'Groq API error: {response.status_code}',
                        'details': response.text
                    }, response.status_code

            except requests.Timeout:
                return {
                    'success': False,
                    'error': 'Request timed out'
                }, 504
            except Exception as e:
                return {
                    'success': False,
                    'error': str(e)
                }, 500

    class _Analyze(Resource):
        """
        Text analysis endpoint - POST /api/groq/analyze
        Supports: summarize, sentiment, keywords, custom
        """
        def post(self):
            try:
                api_key = get_groq_api_key()
                if not api_key:
                    return {'success': False, 'error': 'GROQ_API_KEY not configured'}, 500

                data = request.get_json() or {}
                text = data.get('text', '')
                task = data.get('task', 'summarize')

                if not text:
                    return {'success': False, 'error': 'text field is required'}, 400

                prompts = {
                    'summarize': f"Summarize this text concisely:\n\n{text}\n\nProvide a clear summary in 2-3 sentences.",
                    'sentiment': f"Analyze the sentiment of this text:\n\n{text}\n\nRespond with JSON: {{\"sentiment\": \"positive/negative/neutral\", \"confidence\": 0.0-1.0, \"explanation\": \"brief reason\"}}",
                    'keywords': f"Extract the main keywords from this text:\n\n{text}\n\nRespond with JSON: {{\"keywords\": [\"word1\", \"word2\"], \"topics\": [\"topic1\", \"topic2\"]}}",
                    'custom': data.get('custom_prompt', f"Analyze this text:\n\n{text}")
                }

                prompt = prompts.get(task, prompts['summarize'])

                response = requests.post(
                    get_groq_server(),
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        "model": DEFAULT_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a text analysis expert. Respond clearly and concisely."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500
                    },
                    timeout=30
                )

                if response.status_code == 200:
                    api_data = response.json()
                    return {
                        'success': True,
                        'analysis': api_data['choices'][0]['message']['content'],
                        'task': task
                    }, 200
                else:
                    return {
                        'success': False,
                        'error': f'Analysis failed: {response.status_code}'
                    }, response.status_code

            except Exception as e:
                return {'success': False, 'error': str(e)}, 500

    class _Models(Resource):
        """
        List available models - GET /api/groq/models
        """
        def get(self):
            return {
                'success': True,
                'models': AVAILABLE_MODELS,
                'default': DEFAULT_MODEL
            }, 200

    class _Health(Resource):
        """
        Health check - GET /api/groq/health
        """
        def get(self):
            api_key = get_groq_api_key()
            return {
                'success': True,
                'status': 'healthy' if api_key else 'api_key_missing',
                'api_key_configured': bool(api_key)
            }, 200

    # Register all endpoints
    api.add_resource(_Generate, '/groq')           # Original endpoint
    api.add_resource(_Chat, '/groq/chat')          # Enhanced chat
    api.add_resource(_Analyze, '/groq/analyze')    # Text analysis
    api.add_resource(_Models, '/groq/models')      # List models
    api.add_resource(_Health, '/groq/health')      # Health check
