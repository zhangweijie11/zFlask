# save this as app.py
from flask import Flask, current_app
from blue import auth_bp

app = Flask(__name__)
app.register_blueprint(auth_bp)


@app.before_request
def before_request():
    print("before request")


@app.after_request
def after_request(response):
    print("after request")
    return response


@app.route("/")
def hello():
    return "Hello, World!"


if __name__ == '__main__':
    app.run(debug=True)
