from flask import Blueprint, request, jsonify
from api.FaceRecognitionService import FaceRecognitionService

face_recognition_api_blueprint = Blueprint('face_recognition_api', __name__, url_prefix='/api/face')

@face_recognition_api_blueprint.route('/identify', methods=['POST'])
def identify():
    """Endpoint to identify a face from a base64 image using orchestrator."""
    try:
        data = request.get_json()
        if not data or 'image' not in data:
            return jsonify({'message': 'No image provided'}), 400

        # Get Spring JWT token from cookies
        spring_token = request.cookies.get('jwt_java_spring')
        if not spring_token:
            return jsonify({'message': 'Authentication required'}), 401

        threshold = data.get('threshold')
        if threshold is not None:
            threshold = float(threshold)
            
        token = f"Bearer {spring_token}"
        result = FaceRecognitionService.identify_face_workflow(data['image'], threshold=threshold, token=token)

        
        return jsonify(result), 200

    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': f'Server error: {str(e)}'}), 500

@face_recognition_api_blueprint.route('/register', methods=['POST'])
def register():
    """Endpoint to register a labeled face image using orchestrator."""
    try:
        data = request.get_json()
        if not data or 'image' not in data or 'label' not in data:
            return jsonify({'message': 'Image and label required'}), 400

        # Controller only calls the orchestrator
        embedding = FaceRecognitionService.register_face_workflow(data['label'], data['image'])
        
        return jsonify({'message': 'Face registered successfully', 'embedding': embedding}), 200


    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        return jsonify({'message': f'Server error: {str(e)}'}), 500

@face_recognition_api_blueprint.route('/clear', methods=['DELETE'])
def clear():
    """Endpoint to clear the face database."""
    try:
        FaceRecognitionService.clear_database()
        return jsonify({'message': 'Face database cleared'}), 200
    except Exception as e:
        return jsonify({'message': f'Server error: {str(e)}'}), 500
