import base64
import os
import tempfile
import uuid
import shutil
import numpy as np
import requests
import json
from deepface import DeepFace
from flask import current_app, request

class FaceRecognitionService:
    # --- Cache ---
    _embedding_cache = {}  # In-memory cache for base64 -> embedding

    # --- Logic Functions (Atomic) ---

    @staticmethod
    def decode_base64(base64_string):
        """Decodes base64 string to binary."""
        try:
            return base64.b64decode(base64_string)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {str(e)}")

    @staticmethod
    def save_temp_image(image_data):
        """Saves binary data to a temporary file, returns path."""
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        with os.fdopen(fd, 'wb') as f:
            f.write(image_data)
        return temp_path

    @staticmethod
    def get_embedding(img_path):
        """Generates embedding for an image path using VGG-Face."""
        try:
            from PIL import Image
            img = Image.open(img_path)
            print(f"Analyzing image: {img.size} {img.format}")
            
            results = DeepFace.represent(img_path=img_path, model_name="VGG-Face", enforce_detection=False)
            if results and len(results) > 0:
                embedding = results[0]["embedding"]
                # Check if embedding is all zeros or too small
                if all(v == 0 for v in embedding[:10]): # Simple check for empty/failed embedding
                    print("Warning: DeepFace returned a near-zero embedding. Face might not be detected correctly.")
                return embedding
            return None
        except Exception as e:
            print(f"Embedding error: {e}")
            return None

    @staticmethod
    def calculate_distance(embedding1, embedding2):
        """Calculates cosine distance (1 - cosine similarity)."""
        a = np.array(embedding1)
        b = np.array(embedding2)
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 1.0
        similarity = dot / (norm_a * norm_b)
        return 1.0 - similarity

    @staticmethod
    def sanitize_label(label):
        """Sanitizes labels for file system safety."""
        return ''.join(c for c in label if c.isalnum() or c in ('-', '_')).strip()

    @staticmethod
    def cleanup_path(path):
        """Removes a file safely."""
        if path and os.path.exists(path):
            os.remove(path)

    # --- Orchestrator Functions (Workflows) ---

    @classmethod
    def identify_face_workflow(cls, base64_image, threshold=0.4, token=None):
        """Orchestrates decoding, embedding generation, and DB matching via Spring."""
        # Strip potential data URL prefix
        if "," in base64_image:
            base64_image = base64_image.split(",")[1]

        img_data = cls.decode_base64(base64_image)
        temp_path = cls.save_temp_image(img_data)
        
        try:
            current_embedding = cls.get_embedding(temp_path)
            if not current_embedding:
                return {'match': False, 'message': 'Could not process face'}

            # Fetch existing faces from Spring (Centralized Storage)
            # Environment detection: Use production URL if requested from the deployed domain
            is_prod = 'opencodingsociety.com' in request.host
            spring_base_url = "https://spring.opencodingsociety.com" if is_prod else "http://localhost:8585"
            spring_url = f"{spring_base_url}/api/person/faces"
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Extract token from "Bearer <token>" format
            jwt_token = None
            if token and token.startswith('Bearer '):
                jwt_token = token[7:]  # Remove "Bearer " prefix
            
            try:
                print(f"Fetching faces from Spring: {spring_url}")
                print(f"JWT token present: {jwt_token is not None}")
                
                # Create a session to handle cookies
                import requests
                session = requests.Session()
                
                # Set the JWT token as a cookie
                if jwt_token:
                    cookie_domain = 'spring.opencodingsociety.com' if is_prod else 'localhost'
                    session.cookies.set('jwt_java_spring', jwt_token, domain=cookie_domain, path='/')
                
                resp = session.get(spring_url, headers=headers, timeout=5)
                if resp.status_code != 200:
                    print(f"Spring API error response: {resp.text}")
                    return {'match': False, 'message': f'Spring API error: {resp.status_code}'}
                
                faces_data = resp.json()
                print(f"Successfully fetched {len(faces_data)} faces from Spring")
            except Exception as e:
                print(f"Connection error to Spring: {str(e)}")
                return {'match': False, 'message': f'Connection error to Spring: {str(e)}'}


            print(f"Comparing current face with {len(faces_data)} stored faces.")

            min_dist = float('inf')
            best_match = None

            for face in faces_data:
                stored_data = face.get('faceData')
                uid = face.get('uid', 'unknown')
                if not stored_data:
                    print(f"No face data for {uid}")
                    continue
                
                try:
                    stored_embedding = None
                    if isinstance(stored_data, list):
                        stored_embedding = stored_data
                        print(f"Using direct list embedding for {uid}")
                    elif isinstance(stored_data, str) and (stored_data.strip().startswith('[') or ',' in stored_data[:20]):
                        # Check if it's a JSON array (legacy embedding)
                        if stored_data.strip().startswith('['):
                            try:
                                stored_embedding = json.loads(stored_data)
                                print(f"Parsed JSON embedding for {uid}")
                            except:
                                pass
                    
                    if not stored_embedding:
                        # Treat as base64 image
                        stored_b64 = stored_data
                        if "," in stored_b64:
                            stored_b64 = stored_b64.split(",")[1]

                        # Check cache
                        if stored_b64 in cls._embedding_cache:
                            stored_embedding = cls._embedding_cache[stored_b64]
                            print(f"Using cached embedding for {uid}")
                        else:
                            print(f"Generating embedding from base64 for {uid}")
                            s_img_data = cls.decode_base64(stored_b64)
                            s_temp_path = cls.save_temp_image(s_img_data)
                            try:
                                stored_embedding = cls.get_embedding(s_temp_path)
                                if stored_embedding:
                                    cls._embedding_cache[stored_b64] = stored_embedding
                            finally:
                                cls.cleanup_path(s_temp_path)

                    if not stored_embedding:
                        print(f"Failed to get embedding for {uid}")
                        continue

                    dist = cls.calculate_distance(current_embedding, stored_embedding)
                    print(f"Match candidate {uid}: distance={dist:.4f}")
                    
                    if dist < min_dist:
                        min_dist = dist
                        best_match = uid
                except Exception as e:
                    print(f"Comparison error for {uid}: {e}")
                    continue

            if best_match and min_dist <= (threshold or 0.4):
                # Fetch name from Spring
                name = best_match
                try:
                    is_prod = 'opencodingsociety.com' in request.host
                    spring_base_url = "https://spring.opencodingsociety.com" if is_prod else "http://localhost:8585"
                    name_resp = requests.get(f"{spring_base_url}/api/person/uid/{best_match}", headers=headers)
                    if name_resp.ok:
                        name = name_resp.json().get('name', best_match)
                except:
                    pass
                    
                return {
                    'match': True,
                    'uid': best_match,
                    'name': name,
                    'distance': float(min_dist)
                }
            
            msg = f"No match found (best dist: {min_dist:.2f})" if min_dist < 1.0 else "No face detected"
            return {'match': False, 'message': msg}
            
        finally:
            cls.cleanup_path(temp_path)

    @classmethod
    def register_face_workflow(cls, label, base64_image):
        """Generates and returns an embedding for registration (Verification only)."""
        # Strip potential data URL prefix
        if "," in base64_image:
            base64_image = base64_image.split(",")[1]

        img_data = cls.decode_base64(base64_image)
        temp_path = cls.save_temp_image(img_data)
        try:
            embedding = cls.get_embedding(temp_path)
            if not embedding:
                raise ValueError("DeepFace failed to generate embedding")
            return embedding # Returns list of floats
        finally:
            cls.cleanup_path(temp_path)

    @staticmethod
    def clear_database():
        """Clears local labeled_faces folder for legacy cleanup."""
        uploads = current_app.config.get('UPLOAD_FOLDER')
        if not uploads:
            return False
        # No local storage used anymore
        return True
