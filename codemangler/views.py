import imp
import json
import subprocess
import sys
import tempfile
import os
from functools import wraps

from bson import ObjectId, errors
from flask import request, render_template, url_for, redirect, session

from codemangler import app, db, bcrypt
from codemangler.user import Get, User, Create
from config import MongoConfig

INDENTATION_AMOUNT = 4


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            return redirect(url_for('get_login'))

    return wrap


@app.route('/login', methods=['GET'])
def get_login():
    return render_template('login.html')


@app.route('/signup', methods=['GET'])
def get_register():
    return render_template('signup.html')


@app.route('/login', methods=['POST'])
def login_user():
    username = request.form["username"]
    if MongoConfig.user.find_one({'username': username}):
        user = Get(username).get()
        if bcrypt.check_password_hash(user.password, request.form["password"]):
            session['username'] = user.username
            session['logged_in'] = True
            return redirect(url_for('get_questions'))
        else:
            return render_template('login.html', error='Incorrect password!')
    return render_template('login.html', error='Username not found!')


@app.route('/signup', methods=['POST'])
def signup():
    username_check = MongoConfig.user.find({'username': request.form['username']}).count() > 0
    email_check = MongoConfig.user.find({'email': request.form['email']}).count() > 0
    if username_check and email_check:
        return render_template('signup.html', error='Username & Email already exist!')
    elif username_check:
        return render_template('signup.html', error='Username already exists!')
    elif email_check:
        return render_template('signup.html', error='Email already exists!')
    else:
        user = User(
            request.form['username'],
            request.form['repeat-password'],
            request.form['first-name'],
            request.form['last-name'],
            request.form['email']
        )
        Create(user).populate()
        session['username'] = user.username
        session['logged_in'] = True
        return redirect(url_for('get_questions'))


@app.route('/logout')
@login_required
def logout():
    session.pop('username', None)
    session.pop('logged_in', None)
    return redirect(url_for('get_login'))


@app.route('/')
@login_required
def get_questions():
    if 'logged_in' in session and 'username' in session:
        user = Get(session['username']).get()
    questions = db.questions.find()
    return render_template('questions.html', questions=questions, name=user.first_name + " " + user.last_name)


@app.route('/upload')
@login_required
def upload_page():
    if 'logged_in' in session and 'username' in session:
        user = Get(session['username']).get()
    return render_template('upload.html', name=user.first_name + " " + user.last_name)


@app.route('/question/<question_id>', methods=['GET'])
@login_required
def get_question(question_id):
    question = get_question_from_id(question_id)
    if not question:
        return 'Question not found', 404

    solution = question['solution']
    scramble_order = question['scramble_order']

    return render_template('question.html', question=question, lines=[solution[i].lstrip() for i in scramble_order])


RESPONSE_SUCCESS = 'Correct'
RESPONSE_FAILED = 'Try Again'


def run_test_cases(question, given_order, given_indentation):
    lines = [question['solution'][i].strip() for i in question['scramble_order']]

    code = ''
    for i, val in enumerate(given_order):
        code += ' ' * given_indentation[i] * INDENTATION_AMOUNT + lines[val] + "\n"

    for test_case in question['test_cases']:
        code += "\n" + test_case

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(bytes(code, 'UTF-8'))

    try:
        res = subprocess.run(["python", f.name], timeout=1) # TODO: pass in python location as an arg so you can specify
        res.check_returncode()
    except Exception as e:
        return RESPONSE_FAILED
    finally:
        os.remove(f.name)

    return RESPONSE_SUCCESS

@app.route('/question/<question_id>', methods=['POST'])
@login_required
def answer_question(question_id):
    question = get_question_from_id(question_id)
    if not question:
        return 'Question not found', 404

    given_order = json.loads(request.form.get('order', '[]'))
    given_indentation = json.loads(request.form.get('indentation', '[]'))
    correct_indentation = [int(len(line) - len(line.lstrip())) / INDENTATION_AMOUNT for line in question['solution']]

    order_correct = all([question['scramble_order'][val] == i for i, val in enumerate(given_order)])
    indentation_correct = given_indentation == correct_indentation

    if order_correct and indentation_correct:
        return RESPONSE_SUCCESS

    if 'test_cases' not in question:
        return RESPONSE_FAILED


    return run_test_cases(question, given_order, given_indentation)


def get_question_from_id(question_id):
    try:
        qid = ObjectId(question_id)
    except errors.InvalidId as e:
        return None

    return db.questions.find_one({"_id": qid})
