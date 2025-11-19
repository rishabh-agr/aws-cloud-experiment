
"""
ECGenius Flask API (single file)

Endpoints:
- GET  /          -> Basic project info + list of APIs
- POST /predict   -> Run ECG sample list (len=2500) through 4 functions and return outputs
"""

from flask import Flask, request, jsonify

app = Flask(__name__)


import datetime
from flask import Flask, request

app = Flask(__name__)

@app.before_request
def log_request():
    # Simple log to stdout (captured by systemd/gunicorn)
    print("\n========== ECGenius Request ==========")
    print("⏱ Time:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("🔗 Method:", request.method)
    print("📍 Endpoint:", request.path)
    print("📦 Body:", request.get_data(as_text=True))
    print("======================================\n")

# ==============================
# 🔧 PLACEHOLDER FUNCTIONS
# ==============================
# Replace the bodies of these with your real logic.
# Each function should accept `samples` (a list of 2500 values) and return something JSON-serializable.

def atrial_fibrillation(samples):
    return False

def bundle_branch_block(samples):
    return False

def myocardial_infraction(samples):
    return False

def venticular_fibrillation(samples):
    return False

def heart_rate(samples):
    return 72.5

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
                "description": "Takes a list of 2500 ECG samples and runs 4 functions.",
                "input_format_example": {
                    "samples": [0.12, -0.03, 0.45, "... 2497 more values ..."]
                }
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
        "samples": [v1, v2, ..., v2500]
    }
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

    # (Optional) Check that all values are numeric
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
        # Catch any error from your custom functions
        return jsonify({"error": "Internal error in prediction functions.", "details": str(e)}), 500

    response = {
        "project": "ECGenius",
        "num_samples": len(samples),
        "results": {
            "atrial_fibrillation": afb,
            "bundle_branch_block": bbb,
            "myocardial_infraction": mci,
            "venticular_fibrillation": vfb,
            "heart_rate": hrt
        }
    }

    return jsonify(response), 200


# ==============================
# 🚀 MAIN
# ==============================

if __name__ == "__main__":
    # On EC2, make sure security group allows this port (e.g. 5000 or behind Nginx).
    app.run(host="0.0.0.0", port=5000, debug=False)
