
from flask import Flask, request, jsonify
import os
import logging
import random
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, date
import boto3
from botocore.exceptions import ClientError



# from helper.db import save_prediction_to_db
# from helper.db import get_prediction_from_db
# from helper.db import register_patient_in_db
# from helper.db import update_patient_info_in_db

# from helper.prediction_id import now_iso_utc
# from helper.prediction_id import generate_prediction_id

# from disease_algo.common import myocardial_infraction
# from disease_algo.common import venticular_fibrillation
# from disease_algo.common import atrial_fibrillation
# from disease_algo.common import bundle_branch_block
# from disease_algo.common import heart_rate

app = Flask(__name__)


# ========= LOGGING SETUP =========
LOG_FILE = "/home/ubuntu/logs/ecgenius_logs.txt"

# Make sure directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Create rotating file handler (so log file doesn’t grow forever)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3              # keep 3 old files
)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)
file_handler.setFormatter(formatter)

# Also log to console (so you still see logs in SSH)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# Attach handlers to Flask app logger
app.logger.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)
# ========= END LOGGING SETUP =========


# (OPTIONAL) log every incoming request
@app.before_request
def log_request():
    app.logger.info(
        f"REQUEST: {request.remote_addr} {request.method} {request.path} "
        f"args={dict(request.args)} json={request.get_json(silent=True)}"
    )


# ========= DYNAMODB SETUP =========
DYNAMO_TABLE_NAME = os.getenv("DYNAMO_TABLE_NAME", "ECGeniusPredictions")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
pred_table = dynamodb.Table(DYNAMO_TABLE_NAME)

def save_prediction_to_db(
    prediction_id: str,
    timestamp: str,
    is_mci: bool,
    is_afib: bool,
    is_bbb: bool,
    is_vfi: bool,
    samples
):
    """
    Save a prediction record to DynamoDB.

    Fields:
    - prediction_id (PK)
    - timestamp
    - is_mci, is_afib, is_bbb, is_vfi
    - is_already_visited (False at creation)
    - samples (JSON string)
    """
    import json

    item = {
        "prediction_id": prediction_id,
        "timestamp": timestamp,
        "is_mci": is_mci,
        "is_afib": is_afib,
        "is_bbb": is_bbb,
        "is_vfi": is_vfi,
        "is_already_visited": False,
        "samples": json.dumps(samples),
    }

    app.logger.info(f"Saving prediction to DynamoDB: {prediction_id}")
    pred_table.put_item(Item=item)


def get_prediction_from_db(prediction_id: str):
    """
    Fetch a prediction item from DynamoDB by prediction_id.
    """
    try:
        resp = pred_table.get_item(Key={"prediction_id": prediction_id})
    except ClientError as e:
        app.logger.error(f"DynamoDB get_item error: {e}")
        return None
    return resp.get("Item")

def register_patient_in_db(
    prediction_id: str,
    name: str,
    age,
    gender: str,
    phone_no: str,
    previous_medication: str,
):
    """
    Register patient info for a given prediction_id.

    - Only allowed if is_already_visited is False or not set.
    - Sets is_already_visited = True.
    - Also stores: name, age, gender, phone_no, previous_medication.

    Returns:
      - dict of updated attributes on success
      - "ALREADY_REGISTERED" if already registered
      - None on other error
    """
    try:
        resp = pred_table.update_item(
            Key={"prediction_id": prediction_id},
            # only allow register if not visited/registered yet
            ConditionExpression="attribute_not_exists(is_already_visited) OR is_already_visited = :false",
            UpdateExpression=(
                "SET #name = :name, age = :age, gender = :gender, "
                "phone_no = :phone_no, previous_medication = :pm, "
                "is_already_visited = :true"
            ),
            ExpressionAttributeNames={
                "#name": "name"
            },
            ExpressionAttributeValues={
                ":name": name,
                ":age": age,
                ":gender": gender,
                ":phone_no": phone_no,
                ":pm": previous_medication,
                ":true": True,
                ":false": False,
            },
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            app.logger.info(
                f"Patient already registered for prediction_id={prediction_id}"
            )
            return "ALREADY_REGISTERED"
        app.logger.error(f"DynamoDB update_item error in register_patient_in_db: {e}")
        return None


def update_patient_info_in_db(
    prediction_id: str,
    name: str,
    age,
    gender: str,
    previous_medication: str,
):
    """
    Update patient info only if is_already_visited is False or not set.
    Then set is_already_visited = True.

    Returns:
      - dict of updated attributes on success
      - "ALREADY_VISITED" if condition failed
      - None on other error
    """
    try:
        resp = pred_table.update_item(
            Key={"prediction_id": prediction_id},
            ConditionExpression="attribute_not_exists(is_already_visited) OR is_already_visited = :false",
            UpdateExpression=(
                "SET #name = :name, age = :age, gender = :gender, "
                "previous_medication = :pm, is_already_visited = :true"
            ),
            ExpressionAttributeNames={
                "#name": "name"
            },
            ExpressionAttributeValues={
                ":name": name,
                ":age": age,
                ":gender": gender,
                ":pm": previous_medication,
                ":true": True,
                ":false": False,
            },
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            app.logger.info(
                f"Patient info already updated for prediction_id={prediction_id}"
            )
            return "ALREADY_VISITED"
        app.logger.error(f"DynamoDB update_item error: {e}")
        return None



def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_prediction_id() -> str:
    """
    ID format: YYYYMMDD-xxxxxxxx
    Example: 20251125-183012-1a2b3c4d
    """
    ts = date.today()
    rand = os.urandom(4).hex()  # 8 hex chars
    return f"{ts}-{rand}"




# ==============================
# 🔧 PREDICTION FUNCTIONS
# ==============================


def atrial_fibrillation(samples):
    return False

def bundle_branch_block(samples):
    return False

def myocardial_infraction(samples):
    return False

def venticular_fibrillation(samples):
    return False

def heart_rate(samples):
    return random.randint(70, 75)



# ==============================
#  HOME ENDPOINT
# ==============================

@app.route("/", methods=["GET"])
def home():
    welcome_msg = """
        Welcome to ECGenius - Healthy Heart - Anytime, Anywhere

        _||_ Author - Rishabh Kumar
        _||_ Cloud - Amazon Web Service
        _||_ Service - EC2 (Elastic Compute Cloud)
"""
    return welcome_msg, 200


# ==============================
#  API info ENDPOINT
# ==============================

@app.route("/api", methods=["GET"])
def api():
    """
    Shows basic info about ECGenius and the available APIs.
    """
    info = {
        "project": "ECGenius - Healthy Heart - Anytime, Anywhere",
        "description": (
            "ECGenius takes raw ECG samples, runs them through multiple analysis "
            "functions / models, and returns risk or diagnostic insights."
        ),
        "author": "Rishabh Kumar",
        "apis": {
            "/api": {
                "method": "GET",
                "description": "Project info and list of APIs."
            },
            "/predict": {
                "method": "POST",
                "description": "Takes a list of ECG samples, computes 4 outputs, "
                               "stores them in DynamoDB and returns prediction_id.",
                "input_format_example": {
                    "samples": [0.12, -0.03, 0.45, "... more values ..."]
                }
            },
            "/register": {
                "method": "GET/POST",
                "description": "Takes prediction_id and returns stored prediction + patient info."
            },
            "/get_report": {
                "method": "POST",
                "description": "Update name/age/gender/previous_medication once, "
                               "only if not already visited."
            }
        }
    }
    return jsonify(info), 200


# ==============================
#  PREDICT ENDPOINT
# ==============================

@app.route("/predict", methods=["GET"])
def predict_get_err_msg():
    predict_get_error_msg = """
        Welcome to ECGenius!

        __][__ GET method is not allowed in "/predict", go for POST method.
"""
    return predict_get_error_msg, 200


@app.route("/predict", methods=["POST"])
def predict():
    """
    Expect JSON:
    {
        "samples": [v1, v2, ..., vN]
    }

    Flow:
    - validate samples
    - run 4 functions
    - generate prediction_id + timestamp
    - save all info to DynamoDB
    - return prediction_id + flags
    """
    data = request.get_json(silent=True)

    if data is None:
        return jsonify({"error": "Request body must be JSON."}), 400

    if "samples" not in data:
        return jsonify({"error": "Missing 'samples' field in JSON body."}), 400

    samples = data["samples"]

    # Basic validation
    if not isinstance(samples, list):
        return jsonify({"error": "'samples' must be a list."}), 400

    # if len(samples) != 2500:
    #     return jsonify({
    #         "error": "Invalid number of samples.",
    #         "expected_length": 2500,
    #         "received_length": len(samples)
    #     }), 400

    # Ensure all numeric
    try:
        samples = [float(x) for x in samples]
    except (TypeError, ValueError):
        return jsonify({"error": "All values in 'samples' must be numeric."}), 400

    # Run through your four functions
    try:
        afb = atrial_fibrillation(samples)
        bbb = bundle_branch_block(samples)
        mci = myocardial_infraction(samples)
        vfb = venticular_fibrillation(samples)
        hrt = heart_rate(samples)
    except Exception as e:
        app.logger.exception("Error in prediction functions")
        return jsonify({"error": "Internal error in prediction functions.", "details": str(e)}), 500

    # Convert to your flag names
    is_afib = bool(afb)
    is_bbb = bool(bbb)
    is_mci = bool(mci)
    is_vfi = bool(vfb)

    # Generate ID + timestamp
    prediction_id = generate_prediction_id()
    ts = now_iso_utc()

    # Save to DynamoDB
    try:
        save_prediction_to_db(
            prediction_id=prediction_id,
            timestamp=ts,
            is_mci=is_mci,
            is_afib=is_afib,
            is_bbb=is_bbb,
            is_vfi=is_vfi,
            samples=samples,
        )
    except Exception as e:
        app.logger.exception("Failed to save prediction to DynamoDB")
        return jsonify({"error": "Failed to store prediction.", "details": str(e)}), 500

    app.logger.info(f"Prediction stored successfully: {prediction_id}")

    response = {
        "project": "ECGenius",
        "num_samples": len(samples),
        "prediction_id": prediction_id,
        "timestamp": ts,
        "results": {
            "is_mci": is_mci,
            "is_afib": is_afib,
            "is_bbb": is_bbb,
            "is_vfi": is_vfi,
            "heart_rate": hrt
        }
    }

    return jsonify(response), 200


# ==============================
#  GENERATE REPORT ENDPOINT
# ==============================

@app.route("/register", methods=["POST"])
def register():
    """
    Register a new patient for a given prediction_id.

    Body:
    {
      "prediction_id": "...",
      "name": "Rishabh Kumar",
      "age": 23,
      "gender": "M",
      "phone_no": "9876543210",
      "previous_medication": "Atorvastatin, Aspirin"
    }

    Rules:
    - If prediction_id does not exist -> error.
    - If already registered -> cannot register again.
    """
    body = request.get_json(silent=True) or {}

    prediction_id = body.get("prediction_id")
    name = body.get("name")
    age = body.get("age")
    gender = body.get("gender")
    phone_no = body.get("phone_no")
    previous_medication = body.get("previous_medication")

    missing = [
        k for k in ["prediction_id", "name", "age", "gender", "phone_no", "previous_medication"]
        if body.get(k) is None
    ]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # Ensure prediction exists
    item = get_prediction_from_db(prediction_id)
    if not item:
        return jsonify({"error": "Prediction not found"}), 404

    # Try to register
    updated = register_patient_in_db(
        prediction_id=prediction_id,
        name=name,
        age=age,
        gender=gender,
        phone_no=phone_no,
        previous_medication=previous_medication,
    )

    if updated == "ALREADY_REGISTERED":
        return jsonify({
            "error": "Patient already registered for this prediction_id",
            "prediction_id": prediction_id
        }), 409

    if updated is None:
        return jsonify({"error": "Failed to register patient"}), 500

    return jsonify({
        "message": "Patient registered successfully",
        "prediction_id": prediction_id,
        "record": updated
    }), 200

@app.route("/get_report", methods=["POST"])
def get_report():
    """
    GET:  /get_report?prediction_id=...
    POST: { "prediction_id": "..." }

    Rules:
    - If prediction does not exist -> 404
    - If patient not registered (is_already_visited is False/absent) -> error
    - Else -> return prediction result
    """
    
    payload = request.get_json(silent=True) or {}
    prediction_id = payload.get("prediction_id")

    if not prediction_id:
        return jsonify({"error": "prediction_id is required"}), 400

    item = get_prediction_from_db(prediction_id)
    if not item:
        return jsonify({"error": "Prediction not found"}), 404

    # Enforce: must be registered first
    if not item.get("is_already_visited", False):
        return jsonify({
            "error": "Patient not registered for this prediction_id. Please register first.",
            "prediction_id": prediction_id
        }), 403

    # Build prediction-only result (no PHI if you want it clean)
    report = {
        "prediction_id": item["prediction_id"],
        "timestamp": item["timestamp"],
        "results": {
            "is_mci": item.get("is_mci"),
            "is_afib": item.get("is_afib"),
            "is_bbb": item.get("is_bbb"),
            "is_vfi": item.get("is_vfi"),
        },
        "name": item.get("name"),
        "age": item.get("age"),
        "gender": item.get("gender"),
        "phone_no": item.get("phone_no"),
        "previous_medication": item.get("previous_medication"),
        "samples": item.get("samples")
    }

    return jsonify({"report": report}), 200



# ==============================
# 🚀 MAIN
# ==============================

if __name__ == "__main__":
    # On EC2, make sure security group allows this port (e.g. 5000 or behind Nginx).
    app.run(host="0.0.0.0", port=5000, debug=False)
