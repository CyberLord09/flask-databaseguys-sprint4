# api/api_ainpc.py
import os
import requests
from flask import Blueprint, request, jsonify
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file first
load_dotenv()

# Blueprint for AI NPC API
ainpc_api = Blueprint('ainpc_api', __name__, url_prefix='/api/ainpc')

# Load Gemini API key from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("⚠️ WARNING: GEMINI_API_KEY not set in environment!")
else:
    print("✓ GEMINI_API_KEY loaded successfully!")

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
        "system": "You are a helpful and friendly NPC in a fantasy world. Be conversational, engaging, and respond naturally to what the player says. Keep responses to 2-3 sentences naturally.",
        "greeting": "Hello there! It's nice to meet you. How can I help?"
    }
}


@ainpc_api.route('/prompt', methods=['POST'])
def ai_npc_prompt():
    """Main endpoint: receive user message and return AI NPC response"""
    try:
        data = request.json
        prompt = data.get("prompt", "").strip()
        session_id = data.get("session_id", "default")
        npc_type = data.get("npc_type", "default").lower()
        knowledge_context = data.get("knowledgeContext", "")

        if not prompt:
            return jsonify({"status": "error", "message": "Prompt cannot be empty"}), 400

        # Initialize conversation history for this session
        if session_id not in conversation_history:
            conversation_history[session_id] = []

        # Get NPC personality based on npc_type
        npc_config = npc_personalities.get(npc_type, npc_personalities["default"])
        system_prompt = npc_config["system"]

        # Add knowledge context if provided
        if knowledge_context:
            system_prompt += f"\n\nAdditional context: {knowledge_context}"

        # If no API key, use fallback
        if not GEMINI_API_KEY:
            ai_response = generate_fallback_response(prompt, npc_type)
            conversation_history[session_id].append({"role": "user", "content": prompt})
            conversation_history[session_id].append({"role": "assistant", "content": ai_response})
            return jsonify({
                "status": "success",
                "response": ai_response,
                "mode": "fallback"
            })

        # Call Gemini API with full conversation history
        ai_response = call_gemini_api(system_prompt, prompt, conversation_history[session_id])

        if not ai_response:
            # Use fallback if API failed (quota exceeded, no key, etc)
            print("[DEBUG] Gemini API failed, using fallback response")
            ai_response = generate_fallback_response(prompt, npc_type)

        # Store in history
        conversation_history[session_id].append({"role": "user", "content": prompt})
        conversation_history[session_id].append({"role": "assistant", "content": ai_response})

        # Keep history manageable (last 20 messages = 10 exchanges)
        if len(conversation_history[session_id]) > 20:
            conversation_history[session_id] = conversation_history[session_id][-20:]

        return jsonify({
            "status": "success",
            "response": ai_response,
            "mode": "gemini"
        })

    except Exception as e:
        print(f"Error in ai_npc_prompt: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@ainpc_api.route('/greeting', methods=['POST'])
def get_greeting():
    """Get NPC greeting and reset conversation"""
    try:
        data = request.json
        session_id = data.get("session_id", "default")
        npc_type = data.get("npc_type", "default").lower()

        # Reset conversation for new chat
        conversation_history[session_id] = []

        npc_config = npc_personalities.get(npc_type, npc_personalities["default"])
        greeting = npc_config["greeting"]

        return jsonify({
            "status": "success",
            "greeting": greeting,
            "session_id": session_id
        })

    except Exception as e:
        print(f"Error in get_greeting: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@ainpc_api.route('/reset', methods=['POST'])
def reset_conversation():
    """Clear conversation history for a session"""
    try:
        data = request.json
        session_id = data.get("session_id", "default")

        if session_id in conversation_history:
            del conversation_history[session_id]

        return jsonify({
            "status": "success",
            "message": f"Conversation cleared for {session_id}"
        })

    except Exception as e:
        print(f"Error in reset_conversation: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@ainpc_api.route('/test', methods=['GET'])
def test():
    """Test API connectivity"""
    return jsonify({
        "status": "success",
        "message": "aiNPC API is live!",
        "gemini_available": bool(GEMINI_API_KEY)
    })


@ainpc_api.route('/status/<session_id>', methods=['GET'])
def status(session_id):
    """Check conversation status"""
    return jsonify({
        "status": "success",
        "session_id": session_id,
        "conversation_length": len(conversation_history.get(session_id, [])),
        "has_history": session_id in conversation_history
    })


def call_gemini_api(system_prompt, user_message, history):
    """
    Call Gemini API with conversation history for multi-turn dialogue.
    Tries gemini-2.0-flash first, falls back to older models.
    """
    try:
        models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-pro"]
        
        headers = {"Content-Type": "application/json"}

        # Build messages from history
        messages = []
        for turn in history:
            messages.append({
                "role": "user" if turn["role"] == "user" else "model",
                "parts": [{"text": turn["content"]}]
            })

        # Add current message
        messages.append({
            "role": "user",
            "parts": [{"text": user_message}]
        })

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": messages,
            "generationConfig": {
                "temperature": 0.8,
                "maxOutputTokens": 300,
                "topP": 0.95,
                "topK": 40
            }
        }

        print(f"[DEBUG] Attempting Gemini API call with {len(messages)} messages")
        print(f"[DEBUG] GEMINI_API_KEY exists: {bool(GEMINI_API_KEY)}")

        # Try each model
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            
            try:
                print(f"[DEBUG] Trying model: {model}")
                response = requests.post(
                    f"{url}?key={GEMINI_API_KEY}",
                    json=payload,
                    headers=headers,
                    timeout=20
                )

                print(f"[DEBUG] {model} status code: {response.status_code}")

                if response.status_code == 200:
                    result = response.json()
                    print(f"[DEBUG] Response received from {model}")
                    try:
                        ai_response = result["candidates"][0]["content"]["parts"][0]["text"]
                        print(f"✓ Successfully used {model}")
                        return ai_response.strip()
                    except (KeyError, IndexError) as e:
                        print(f"[DEBUG] Parse error with {model}: {str(e)}")
                        print(f"[DEBUG] Response structure: {result}")
                        continue
                elif response.status_code == 429:
                    print(f"[DEBUG] {model} returned 429 - Quota exceeded. Using fallback.")
                    return None  # Signal to use fallback
                else:
                    print(f"[DEBUG] {model} returned {response.status_code}")
                    print(f"[DEBUG] Response: {response.text[:500]}")
                    continue
                    
            except Exception as e:
                print(f"[DEBUG] Exception with {model}: {str(e)}")
                continue
        
        print("[DEBUG] All models failed")
        return None

    except Exception as e:
        print(f"[DEBUG] Error in call_gemini_api: {str(e)}")
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
