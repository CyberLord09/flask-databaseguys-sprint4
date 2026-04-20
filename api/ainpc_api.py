# api/ainpc_api.py
"""
=============================================================================
AI NPC API - Conversational NPCs powered by Gemini
=============================================================================
Provides personality-driven conversational NPCs for game/educational contexts.
Uses the same proven Gemini API approach as gemini_api.py.

FEATURES:
- Multiple NPC personalities (history expert, merchant, guard, wizard, innkeeper)
- Per-session conversation history (maintains context across messages)
- Automatic fallback responses when API unavailable
- Knowledge context injection for educational content

ENDPOINTS:
- POST /api/ainpc/prompt   - Send message to NPC, get response
- POST /api/ainpc/greeting - Get NPC greeting and reset conversation
- POST /api/ainpc/reset    - Clear conversation history
- GET  /api/ainpc/test     - Test API availability
- GET  /api/ainpc/status/<session_id> - Check conversation status
=============================================================================
"""
from __init__ import app
import requests
from flask import Blueprint, request, jsonify, current_app
from flask_restful import Api, Resource

# =============================================================================
# BLUEPRINT SETUP
# =============================================================================

# Blueprint for AI NPC API
ainpc_api = Blueprint('ainpc_api', __name__, url_prefix='/api/ainpc')
api = Api(ainpc_api)

# In-memory conversation history per NPC session
conversation_history = {}

# NPC personality templates
npc_personalities = {
    "history": {
        "system": "You are a knowledgeable history expert who is passionate about sharing historical knowledge. You speak with authority but in a friendly, conversational way. You can discuss ancient civilizations, historical events, famous figures, and their impact on the world. Be engaging and curious about what the player wants to know. Keep responses to 2-3 sentences naturally.",
        "greeting": "Greetings! I'm delighted to discuss history with you. What era or event interests you?"
    },
    "merchant": {
        "system": "You are a friendly tavern merchant who loves talking about goods, trades, and stories. Be conversational, warm, and occasionally mention items or quests. Keep responses to 2-3 sentences naturally.",
        "greeting": "Well hello there, friend! Welcome to my humble shop. What brings you by today?"
    },
    "guard": {
        "system": "You are a professional but personable town guard. You discuss security, local events, and can give directions. Be attentive and protective. Keep responses to 2-3 sentences naturally.",
        "greeting": "Greetings, traveler. Everything alright? Let me know if you need anything."
    },
    "wizard": {
        "system": "You are a mysterious and wise wizard who speaks about magic, ancient lore, and mystical matters. Be enigmatic but helpful. Keep responses to 2-3 sentences naturally.",
        "greeting": "Ah, another seeker of knowledge has arrived. What magical mysteries interest you?"
    },
    "innkeeper": {
        "system": "You are a cheerful innkeeper who loves chatting with guests about their travels, local gossip, and recommendations. Be hospitable and talkative. Keep responses to 2-3 sentences naturally.",
        "greeting": "Welcome, welcome! Come in, come in! Can I get you anything to drink?"
    },
    "default": {
        "system": "You are a helpful and friendly NPC that educates on computer systems and networking. You can explain concepts, answer questions, and provide guidance in a conversational manner. Keep responses to 2-3 sentences naturally.",
        "greeting": "Hello there! It's nice to meet you. How can I help you on your computer science journey today?"
    }
}


# =============================================================================
# ENDPOINTS
# =============================================================================

class AINPCAPI:
    class _Prompt(Resource):
        """
        Main NPC conversation endpoint - POST /api/ainpc/prompt
        Handles conversational exchanges with personality-driven NPCs.
        """
        def post(self):
            """
            Send a message to an NPC and get a response.
            
            Expected JSON body:
            {
                "prompt": "User message",
                "session_id": "unique_session_identifier",
                "npc_type": "history|merchant|guard|wizard|innkeeper|default",
                "knowledgeContext": "Optional additional context"
            }
            
            Returns:
                JSON response with NPC reply and conversation mode
            """

            try:
                body = request.get_json()
                if not body:
                    return {'status': 'error', 'message': 'Request body is required'}, 400
                prompt = body.get("prompt", "").strip()
                session_id = body.get("session_id", "default")
                npc_type = body.get("npc_type", "default").lower()
                knowledge_context = body.get("knowledgeContext", "")
                if not prompt:
                    return {"status": "error", "message": "Prompt cannot be empty"}, 400
                # Initialize conversation history for this session
                if session_id not in conversation_history:
                    conversation_history[session_id] = []
                # Get NPC personality based on npc_type
                npc_config = npc_personalities.get(npc_type, npc_personalities["default"])
                system_prompt = npc_config["system"]
                # Add knowledge context if provided
                if knowledge_context:
                    system_prompt += f"\n\nAdditional context: {knowledge_context}"
                # Check if Gemini API is configured (using centralized app config)
                api_key = app.config.get('GEMINI_API_KEY')
                server = app.config.get('GEMINI_SERVER')
 
                # Call Gemini API with full conversation history (using working approach)
                ai_response = call_gemini_api(system_prompt, prompt, conversation_history[session_id])
                if not ai_response:
                    # Try Groq API as fallback if Gemini fails
                    current_app.logger.info("Gemini API failed, trying Groq API fallback")
                    ai_response = call_groq_api(system_prompt, prompt, conversation_history[session_id])
                    if ai_response:
                        mode = "groq"
                    else:
                        # Use static fallback if both fail
                        current_app.logger.info("Groq API also failed, using static fallback response")
                        ai_response = generate_fallback_response(prompt, npc_type)
                        mode = "fallback"
                else:
                    mode = "gemini"
                    
                # Store in history
                conversation_history[session_id].append({"role": "user", "content": prompt})
                conversation_history[session_id].append({"role": "assistant", "content": ai_response})
                # Keep history manageable (last 20 messages = 10 exchanges)
                if len(conversation_history[session_id]) > 20:
                    conversation_history[session_id] = conversation_history[session_id][-20:]
                return {
                    "status": "success",
                    "response": ai_response,
                    "mode": mode
                }
            except Exception as e:
                current_app.logger.error(f"Error in ai_npc_prompt: {str(e)}")
                return {
                    "status": "error",
                    "message": str(e)
                }, 500

    class _Greeting(Resource):
        """
        NPC greeting endpoint - POST /api/ainpc/greeting
        Get NPC greeting and reset conversation.
        """
        def post(self):
            """
            Get an NPC's greeting message and reset the conversation.
            Expected JSON body:
            {
                "session_id": "unique_session_identifier",
                "npc_type": "history|merchant|guard|wizard|innkeeper|default"
            }
            Returns:
                JSON response with greeting message
            """
            try:
                body = request.get_json()
                if not body:
                    return {'status': 'error', 'message': 'Request body is required'}, 400
                session_id = body.get("session_id", "default")
                npc_type = body.get("npc_type", "default").lower()
                # Reset conversation for new chat
                conversation_history[session_id] = []
                npc_config = npc_personalities.get(npc_type, npc_personalities["default"])
                greeting = npc_config["greeting"]
                return {
                    "status": "success",
                    "greeting": greeting,
                    "session_id": session_id
                }
            except Exception as e:
                current_app.logger.error(f"Error in get_greeting: {str(e)}")
                return {
                    "status": "error",
                    "message": str(e)
                }, 500

    class _Reset(Resource):
        """
        Conversation reset endpoint - POST /api/ainpc/reset
        Clear conversation history for a session.
        """
        def post(self):
            """
            Clear conversation history for a specific session.
            Expected JSON body:
            {
                "session_id": "unique_session_identifier"
            }
            Returns:
                JSON confirmation message
            """
            try:
                body = request.get_json()
                if not body:
                    return {'status': 'error', 'message': 'Request body is required'}, 400
                session_id = body.get("session_id", "default")
                if session_id in conversation_history:
                    del conversation_history[session_id]
                return {
                    "status": "success",
                    "message": f"Conversation cleared for {session_id}"
                }
            except Exception as e:
                current_app.logger.error(f"Error in reset_conversation: {str(e)}")
                return {
                    "status": "error",
                    "message": str(e)
                }, 500

    class _Test(Resource):
        """
        API test endpoint - GET /api/ainpc/test
        Test API connectivity and configuration.
        """
        def get(self):
            """
            Test if AI NPC API is accessible and properly configured.
            Returns:
                JSON response with API status and configuration details
            """
            api_key = app.config.get('GEMINI_API_KEY')
            server = app.config.get('GEMINI_SERVER')
            return {
                "status": "success",
                "message": "aiNPC API is live!",
                "gemini_configured": bool(api_key and server),
                "api_key_present": bool(api_key),
                "server_configured": bool(server)
            }

    class _Status(Resource):
        """
        Session status endpoint - GET /api/ainpc/status/<session_id>
        Check conversation status for a session.
        """
        def get(self, session_id):
            """
            Check conversation status for a specific session.
            Args:
                session_id: Unique session identifier (URL parameter)
            Returns:
                JSON response with session status and conversation length
            """
            return {
                "status": "success",
                "session_id": session_id,
                "conversation_length": len(conversation_history.get(session_id, [])),
                "has_history": session_id in conversation_history
            }
            
    # =============================================================================
    # REGISTER RESOURCES
    # =============================================================================

    # Register resources with their respective endpoints
    api.add_resource(_Prompt, '/prompt')              # POST /api/ainpc/prompt
    api.add_resource(_Greeting, '/greeting')          # POST /api/ainpc/greeting
    api.add_resource(_Reset, '/reset')                # POST /api/ainpc/reset
    api.add_resource(_Test, '/test')                  # GET /api/ainpc/test
    api.add_resource(_Status, '/status/<session_id>') # GET /api/ainpc/status/<session_id>


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def call_gemini_api(system_prompt, user_message, history):
    """
    Call Gemini API with conversation history for multi-turn dialogue.
    Uses the PROVEN working approach from gemini_api.py:
    - Simple payload structure (no system_instruction field)
    - Centralized config from app.config
    - System prompt embedded in the text content
    - Single API call with clear error handling
    """
    try:
        # Get configuration from centralized app config (same as gemini_api.py)
        api_key = app.config.get('GEMINI_API_KEY')
        server = app.config.get('GEMINI_SERVER')
        
        if not api_key or not server:
            current_app.logger.warning("Gemini API not configured, using fallback")
            return None
        
        # Build the endpoint URL with API key
        endpoint = f"{server}?key={api_key}"
        
        # Build conversation context from history
        conversation_context = ""
        if history:
            conversation_context = "\n\nPrevious conversation:\n"
            for turn in history[-10:]:  # Last 10 messages (5 exchanges) for context
                role = "User" if turn["role"] == "user" else "Assistant"
                conversation_context += f"{role}: {turn['content']}\n"
        
        # Combine system prompt, conversation history, and current message
        # This is the WORKING approach from gemini_api.py - put everything in text
        full_prompt = f"{system_prompt}{conversation_context}\n\nUser: {user_message}\n\nAssistant:"
        
        # Use the SIMPLE payload structure that WORKS (from gemini_api.py)
        payload = {
            "contents": [{
                "parts": [{
                    "text": full_prompt
                }]
            }]
        }
        
        current_app.logger.info(f"Making Gemini API request for NPC conversation")
        
        # Make request to Gemini API (same approach as gemini_api.py)
        response = requests.post(
            endpoint,
            headers={'Content-Type': 'application/json'},
            json=payload,
            timeout=20  # 20 second timeout for NPC responses
        )
        
        # Handle response
        if response.status_code == 200:
            result = response.json()
            try:
                ai_response = result['candidates'][0]['content']['parts'][0]['text']
                current_app.logger.info("✓ Gemini API call successful")
                return ai_response.strip()
            except (KeyError, IndexError) as e:
                current_app.logger.error(f"Error parsing Gemini response: {e}")
                return None
        elif response.status_code == 429:
            current_app.logger.warning("Gemini API rate limit exceeded (429)")
            return None  # Signal to use fallback
        else:
            current_app.logger.error(f"Gemini API error: {response.status_code} - {response.text[:200]}")
            return None
                    
    except requests.RequestException as e:
        current_app.logger.error(f"Error communicating with Gemini API: {e}")
        return None
    except Exception as e:
        current_app.logger.error(f"Unexpected error in call_gemini_api: {e}")
        return None
    
    
def call_groq_api(system_prompt, user_message, history):
    """
    Call Groq API with conversation history for multi-turn dialogue.
    Uses the /api/groq/chat endpoint pattern from groq_api.py.
    """
    
    try:
        print("Attempting to call Groq API as fallback...")
        # Get configuration from centralized app config (same as groq_api.py)
        api_key = app.config.get('GROQ_API_KEY') or (hasattr(current_app, 'config') and current_app.config.get('GROQ_API_KEY'))
        server = app.config.get('GROQ_SERVER')
        if not api_key or not server:
            current_app.logger.warning("Groq API not configured, skipping fallback")
            return None

        # Build messages array for Groq (system, then history, then user)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for turn in history[-10:]:
                role = turn["role"]
                content = turn["content"]
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 512
        }

        endpoint = server
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        current_app.logger.info("Making Groq API request for NPC conversation")
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        if response.status_code == 200:
            result = response.json()
            try:
                ai_response = result['choices'][0]['message']['content']
                current_app.logger.info("✓ Groq API call successful")
                return ai_response.strip()
            except (KeyError, IndexError) as e:
                current_app.logger.error(f"Error parsing Groq response: {e}")
                return None
        elif response.status_code == 429:
            current_app.logger.warning("Groq API rate limit exceeded (429)")
            return None
        else:
            current_app.logger.error(f"Groq API error: {response.status_code} - {response.text[:200]}")
            return None

    except requests.RequestException as e:
        current_app.logger.error(f"Error communicating with Groq API: {e}")
        return None
    except Exception as e:
        current_app.logger.error(f"Unexpected error in call_groq_api: {e}")
        return None


def generate_fallback_response(prompt, npc_type):
    """Generate fallback response when API is unavailable"""
    prompt_lower = prompt.lower()

    if any(word in prompt_lower for word in ["hello", "hi", "hey", "greetings"]):
        responses = {
            "history": "Greetings! I'm delighted to discuss history with you.",
            "merchant": "Ah, hello friend! What can I sell you today?",
            "guard": "Hail, traveler. State your business.",
            "wizard": "Greetings, seeker. I sense questions in your mind.",
            "innkeeper": "Welcome! Let me get you a drink!",
            "default": "Hello there, friend!"
        }
        return responses.get(npc_type, responses["default"])

    elif any(word in prompt_lower for word in ["how are you", "how's it going"]):
        responses = {
            "history": "I'm doing well, thank you for asking!",
            "merchant": "I'm doing wonderfully, thanks for asking!",
            "guard": "All is well in town.",
            "wizard": "The arcane energies flow pleasantly today.",
            "innkeeper": "Can't complain! Business is brisk!",
            "default": "I'm doing well, thank you!"
        }
        return responses.get(npc_type, responses["default"])

    elif any(word in prompt_lower for word in ["bye", "goodbye", "farewell"]):
        responses = {
            "history": "May your pursuit of knowledge continue!",
            "merchant": "Come back soon, friend!",
            "guard": "Safe travels, adventurer.",
            "wizard": "May the currents guide your path.",
            "innkeeper": "Farewell, friend!",
            "default": "Goodbye! Safe travels!"
        }
        return responses.get(npc_type, responses["default"])

    else:
        responses = {
            "history": "That's an interesting historical question. Tell me more?",
            "merchant": f"Hmm, {prompt}? Interesting thought!",
            "guard": f"Interesting... {prompt}, you say?",
            "wizard": f"Ah, {prompt}... curious indeed.",
            "innkeeper": f"{prompt}? What a tale!",
            "default": "That's interesting. Tell me more."
        }
        return responses.get(npc_type, responses["default"])
