from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Hello to yash and tushar from AWS Flask backend!"

if __name__ == "__main__":
    app.run(debug=True)
