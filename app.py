from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timezone , timedelta
from functools import wraps
import sqlite3
import os
from init_db import create_tables
import pytz
from math import ceil

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def parse_timestamp(ts):
    if ts is None or ts == "":
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        # fallback if no microseconds part
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Replace with a strong key in production
create_tables()

def get_db_connection():
    conn = sqlite3.connect(os.getenv("DB_PATH", "taskcrafter.db"))
    conn.row_factory = sqlite3.Row
    return conn

# ------------------------ AUTH ROUTES ------------------------

@app.template_filter('to_ist')
def to_ist(value, format="%d %b %Y %I:%M %p"):
    if value is None:
        return "N/A"
    try:
        utc = pytz.utc
        ist = pytz.timezone("Asia/Kolkata")
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        dt_utc = utc.localize(dt)
        dt_ist = dt_utc.astimezone(ist)
        return dt_ist.strftime(format)
    except Exception:
        return "Invalid time"


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            flash('Username already taken.', 'error')
            conn.close()
            return redirect(url_for('signup'))

        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            flash('Email already registered.', 'error')
            conn.close()
            return redirect(url_for('signup'))

        cur.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                    (username, email, password))
        conn.commit()
        conn.close()

        flash('Signup successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['identifier']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ? OR email = ?", (identifier, identifier))
        user = cur.fetchone()
        conn.close()

        if user and password == user['password']:
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('login'))

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        identifier = request.form['identifier']
        new_password = request.form['new_password']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ? OR email = ?", (identifier, identifier))
        user = cur.fetchone()

        if user:
            cur.execute("UPDATE users SET password = ? WHERE id = ?", (new_password, user['id']))
            conn.commit()
            flash('Password updated. Please log in.', 'success')
        else:
            flash('User not found.', 'error')

        conn.close()
        return redirect(url_for('login'))

    return render_template('reset_password.html')

# ------------------------ TASK ROUTES ------------------------



@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, task_name, estimated_time, is_completed, start_time, is_paused
        FROM tasks
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))
    tasks = cur.fetchall()
    conn.close()

    # Just convert row to dict — no formatting
    formatted_tasks = [dict(task) for task in tasks]

    return render_template('dashboard.html', username=session['username'], tasks=formatted_tasks)



@app.route('/add_task', methods=['GET', 'POST'])
@login_required
def add_task():
    if request.method == 'POST':
        task_name = request.form['task_name']
        description = request.form.get('description', '')
        estimated_time = int(request.form['estimated_time'])

        if estimated_time < 1:
            flash("Estimated time must be at least 1 minute.", "error")
            return redirect(url_for('add_task'))

        priority = int(request.form.get('priority', 0))

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO tasks (user_id, task_name, description, estimated_time, priority, is_completed)
            VALUES (?, ?, ?, ?, ?, 0)
        ''', (session['user_id'], task_name, description, estimated_time, priority))
        conn.commit()
        conn.close()

        return redirect(url_for('dashboard'))

    return render_template('add_task.html')

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        task_name = request.form['task_name']
        estimated_time = int(request.form['estimated_time'])

        if estimated_time < 1:
            flash("Estimated time must be at least 1 minute.", "error")
            return redirect(url_for('edit_task', task_id=task_id))

        priority = request.form.get('priority', 0)  # will be string, can convert if needed

        cur.execute('UPDATE tasks SET task_name = ?, estimated_time = ?, priority = ? WHERE id = ? AND user_id = ?',
                    (task_name, estimated_time, priority, task_id, session['user_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))

    cur.execute('SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, session['user_id']))
    task = cur.fetchone()
    conn.close()

    if not task:
        return "Task not found", 404

    return render_template('edit_task.html', task=task)



@app.route('/delete_task/<int:task_id>')
def delete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', (task_id, session['user_id']))
    conn.commit()
    conn.close()

    flash('Task deleted.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/mark_complete/<int:task_id>')
def mark_complete(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch task details
    cur.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, session['user_id']))
    task = cur.fetchone()

    if task:
        if not task['start_time']:
            flash("You must start the task before marking it complete.", "warning")
            conn.close()
            return redirect(url_for('dashboard'))

        try:
            start_time = datetime.strptime(task['start_time'], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            start_time = datetime.strptime(task['start_time'], "%Y-%m-%d %H:%M:%S.%f")

        # ✅ Normalize both times to UTC
        utc = pytz.utc
        start_time_utc = utc.localize(start_time)
        completed_at_utc = datetime.utcnow().replace(tzinfo=utc)

        # ✅ Correct time difference in seconds, then round to minutes
        seconds_elapsed = (completed_at_utc - start_time_utc).total_seconds()
        actual_time_minutes = max(1, ceil(seconds_elapsed / 60))

        # ✅ Insert into completed_tasks table
        cur.execute('''
            INSERT INTO completed_tasks 
            (user_id, task_name, description, estimated_time, actual_time, start_time, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            task['user_id'],
            task['task_name'],
            task['description'],
            task['estimated_time'],
            actual_time_minutes,
            task['start_time'],
            completed_at_utc.strftime("%Y-%m-%d %H:%M:%S")
        ))

        # ✅ Update user_stats table
        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute('SELECT * FROM user_stats WHERE user_id = ? AND date = ?', (session['user_id'], today))
        stats_row = cur.fetchone()

        if stats_row:
            cur.execute('''
                UPDATE user_stats SET tasks_completed = tasks_completed + 1
                WHERE user_id = ? AND date = ?
            ''', (session['user_id'], today))
        else:
            cur.execute('''
                INSERT INTO user_stats (user_id, date, tasks_completed)
                VALUES (?, ?, 1)
            ''', (session['user_id'], today))

        # ✅ Remove from active task list
        cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

        flash("Task marked as Complete!", "success")
    else:
        flash("Task not found!", "error")

    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/start_task/<int:task_id>')
def start_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    utc_now = datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET start_time = ? WHERE id = ? AND user_id = ?",
                (utc_now, task_id, session['user_id']))
    conn.commit()
    conn.close()

    flash("Task started!", "success")
    return redirect(url_for('dashboard'))


@app.route('/pause_task/<int:task_id>')
def pause_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET is_paused = 1 WHERE id = ? AND user_id = ?", (task_id, session['user_id']))
    conn.commit()
    conn.close()
    flash("Task paused.", "info")
    return redirect(url_for('dashboard'))

@app.route('/resume_task/<int:task_id>')
def resume_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET is_paused = 0 WHERE id = ? AND user_id = ?", (task_id, session['user_id']))
    conn.commit()
    conn.close()
    flash("Task resumed.", "success")
    return redirect(url_for('dashboard'))


@app.route('/completed_tasks')
@login_required
def view_completed_tasks():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],))
    user = cur.fetchone()
    username = user['username'] if user else "User"

    filter_option = request.args.get('filter', 'all')  # date filter
    time_filter = request.args.get('time_filter', 'all')  # new time filter

    date_filter_sql = ""
    params = [session['user_id']]

    if filter_option == 'today':
        date_filter_sql = "AND DATE(completed_at) = ?"
        params.append(datetime.now().date())
    elif filter_option == 'last7':
        date_filter_sql = "AND DATE(completed_at) >= ?"
        params.append((datetime.now() - timedelta(days=7)).date())
    elif filter_option == 'last30':
        date_filter_sql = "AND DATE(completed_at) >= ?"
        params.append((datetime.now() - timedelta(days=30)).date())

    cur.execute(f"""
        SELECT * FROM completed_tasks
        WHERE user_id = ? {date_filter_sql}
        ORDER BY completed_at DESC
    """, params)

    rows = cur.fetchall()
    conn.close()

    completed = []
    for row in rows:
        actual = row['actual_time']
        estimated = row['estimated_time']
        qualifies = True

        if time_filter == 'before' and not (actual is not None and actual < estimated):
            qualifies = False
        elif time_filter == 'on' and not (actual is not None and actual == estimated):
            qualifies = False
        elif time_filter == 'after' and not (actual is not None and actual > estimated):
            qualifies = False

        if qualifies:
            completed.append({
                'id': row['id'],
                'user_id': row['user_id'],
                'task_name': row['task_name'],
                'description': row['description'],
                'estimated_time': estimated,
                'created_at': datetime.strptime(row['created_at'], "%Y-%m-%d %H:%M:%S") if row['created_at'] else None,
                'completed_at': datetime.strptime(row['completed_at'], "%Y-%m-%d %H:%M:%S") if row['completed_at'] else None,
                'actual_time': actual
            })

    return render_template(
        'completed.html',
        completed_tasks=completed,
        username=username,
        selected_filter=filter_option,
        selected_time_filter=time_filter
    )


# ------------------------ PROFILE & HOME ------------------------


@app.route('/profile')
@login_required
def profile():
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()

    # Get basic user info
    cur.execute("SELECT username, email, created_at FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    
    # Format created_at for readability
    created_at = datetime.strptime(user['created_at'], "%Y-%m-%d %H:%M:%S")
    formatted_created_at = created_at.strftime("%B %d, %Y")  # e.g., "June 22, 2025"

    # Get stats
    cur.execute("SELECT date, tasks_completed FROM user_stats WHERE user_id = ? ORDER BY date ASC", (user_id,))
    stats = cur.fetchall()

    # Streak
    today = datetime.now().date()
    active_days = {datetime.strptime(row['date'], "%Y-%m-%d").date() for row in stats if row['tasks_completed'] > 0}
    streak = 0
    current_day = today
    while current_day in active_days:
        streak += 1
        current_day -= timedelta(days=1)

    # Best performing day
    best_day = None
    max_tasks = 0
    for row in stats:
        if row['tasks_completed'] > max_tasks:
            max_tasks = row['tasks_completed']
            best_day = row['date']

    # Format best_day
    formatted_best_day = datetime.strptime(best_day, "%Y-%m-%d").strftime("%B %d, %Y") if best_day else None

    conn.close()

    return render_template(
        'profile.html',
        user=user,
        streak=streak,
        best_day=formatted_best_day,
        max_tasks=max_tasks,
        member_since=formatted_created_at,
        username=user['username']
    )



@app.route('/productivity')
def productivity():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    connection = sqlite3.connect('taskcrafter.db')
    cursor = connection.cursor()

    # Get username
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    username = row[0] if row else "User"

    # Total active tasks
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,))
    active_tasks = cursor.fetchone()[0]

    # Total completed tasks
    cursor.execute("SELECT COUNT(*) FROM completed_tasks WHERE user_id = ?", (user_id,))
    completed_tasks = cursor.fetchone()[0]

    # Total tasks = active + completed
    total_tasks = active_tasks + completed_tasks

    # Total estimated time for completed tasks
    cursor.execute("SELECT COALESCE(SUM(estimated_time), 0) FROM completed_tasks WHERE user_id = ?", (user_id,))
    total_estimated = cursor.fetchone()[0]

    # Total actual time
    cursor.execute("SELECT COALESCE(SUM(actual_time), 0) FROM completed_tasks WHERE user_id = ?", (user_id,))
    total_actual = cursor.fetchone()[0]

    # Efficiency
    # Calculate efficiency if actual time > 0 else 0
    efficiency=0
    if total_estimated > total_actual and total_actual==0:
            efficiency = 100.0
    if total_actual > 0:
            efficiency = round((total_estimated / total_actual) * 100, 2)


    connection.close()

    return render_template('productivity.html',
                           total_tasks=total_tasks,
                           total_completed=completed_tasks,
                           total_estimated=total_estimated,
                           total_actual=total_actual,
                           efficiency=efficiency,
                           username=username)


@app.route('/unmark_complete/<int:task_id>', methods=['POST'])
@login_required
def unmark_complete(task_id):
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch task data from completed_tasks
    cur.execute('''
        SELECT task_name, description, estimated_time, actual_time, created_at, completed_at
        FROM completed_tasks
        WHERE id = ? AND user_id = ?
    ''', (task_id, user_id))
    completed_task = cur.fetchone()

    if not completed_task:
        flash("Task not found.", "danger")
        conn.close()
        return redirect(url_for('view_completed_tasks'))

    # Insert back into tasks
    cur.execute('''
        INSERT INTO tasks (user_id, task_name, description, estimated_time, created_at, is_completed)
        VALUES (?, ?, ?, ?, ?, 0)
    ''', (user_id, completed_task['task_name'], completed_task['description'],
          completed_task['estimated_time'], completed_task['created_at']))

    # Decrement from user_stats
    completed_date = completed_task['completed_at'].split()[0]  # "YYYY-MM-DD"
    cur.execute('SELECT tasks_completed FROM user_stats WHERE user_id = ? AND date = ?', (user_id, completed_date))
    row = cur.fetchone()

    if row:
        if row['tasks_completed'] > 1:
            cur.execute('''
                UPDATE user_stats
                SET tasks_completed = tasks_completed - 1
                WHERE user_id = ? AND date = ?
            ''', (user_id, completed_date))
        else:
            # If only 1 task existed, remove the row
            cur.execute('DELETE FROM user_stats WHERE user_id = ? AND date = ?', (user_id, completed_date))

    # Delete from completed_tasks
    cur.execute('DELETE FROM completed_tasks WHERE id = ? AND user_id = ?', (task_id, user_id))

    conn.commit()
    conn.close()

    flash("Task marked as incomplete and moved back to active tasks.", "success")
    return redirect(url_for('dashboard'))



@app.route('/optimize_tasks', methods=['GET', 'POST'])
@login_required
def optimize_tasks():
    user_id = session['user_id']
    optimized_tasks = []
    available_time = None
    leftover_time = None
    total_tasks_remaining = 0
    next_task_fits = None
    strategy = None
    error_message = None

    if request.method == 'POST':
        strategy = request.form.get('strategy')
        available_time_str = request.form.get('available_time')
        available_time = int(available_time_str) if available_time_str and available_time_str.isdigit() else None

        # If strategy requires time but it's missing
        if strategy != 'none' and available_time is None:
            error_message = "Available time is required for the selected strategy."
            return render_template(
                'optimize_tasks.html',
                optimized_tasks=[],
                available_time=None,
                leftover_time=None,
                total_tasks_remaining=0,
                next_task_fits=None,
                strategy=strategy,
                error_message=error_message
            )

        conn = sqlite3.connect('taskcrafter.db')
        c = conn.cursor()

        if strategy == 'priority':
            c.execute("SELECT id, task_name, estimated_time, priority FROM tasks WHERE user_id = ? AND is_completed = 0", (user_id,))
            all_tasks = c.fetchall()
            all_tasks.sort(key=lambda x: x[3])  # Lower priority = more important

        elif strategy == 'longest_job':
            c.execute("SELECT id, task_name, estimated_time FROM tasks WHERE user_id = ? AND is_completed = 0", (user_id,))
            all_tasks = c.fetchall()
            all_tasks.sort(key=lambda x: x[2], reverse=True)  # Longest time first

        elif strategy == 'max_tasks':
            c.execute("SELECT id, task_name, estimated_time FROM tasks WHERE user_id = ? AND is_completed = 0", (user_id,))
            all_tasks = c.fetchall()
            all_tasks.sort(key=lambda x: x[2])  # Shortest time first

        elif strategy == 'none':
            c.execute("SELECT id, task_name, estimated_time, priority FROM tasks WHERE user_id = ? AND is_completed = 0", (user_id,))
            optimized_tasks = c.fetchall()
            conn.close()
            return render_template(
                'optimize_tasks.html',
                optimized_tasks=optimized_tasks,
                available_time=None,
                leftover_time=None,
                total_tasks_remaining=0,
                next_task_fits=None,
                strategy=strategy,
                error_message=None
            )

        else:
            all_tasks = []

        # Filter tasks by available time (only if strategy ≠ 'none')
        if available_time is not None:
            total = 0
            temp = []
            for task in all_tasks:
                task_time = task[2]
                if total + task_time <= available_time:
                    temp.append(task)
                    total += task_time
                else:
                    break
            optimized_tasks = temp
            leftover_time = available_time - total
            total_tasks_remaining = len(all_tasks) - len(optimized_tasks)

            remaining_tasks = all_tasks[len(optimized_tasks):]
            if remaining_tasks:
                next_task_estimated_time = remaining_tasks[0][2]
                next_task_fits = leftover_time >= next_task_estimated_time
            else:
                next_task_fits = None

        conn.close()

    return render_template(
        'optimize_tasks.html',
        optimized_tasks=optimized_tasks,
        available_time=available_time,
        leftover_time=leftover_time,
        total_tasks_remaining=total_tasks_remaining,
        next_task_fits=next_task_fits,
        strategy=strategy,
        error_message=error_message
    )




@app.route('/')
def home():
    return render_template('home.html')



# ------------------------ RUN APP ------------------------

if __name__ == '__main__':
    app.run(debug=True)
