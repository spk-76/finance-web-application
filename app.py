import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, Response, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Get all stocks the user owns
    rows = db.execute(
        "SELECT symbol, SUM(shares) AS shares \
         FROM portfolio WHERE user_id = ? \
         GROUP BY symbol HAVING shares > 0",
        session["user_id"]
    )

    # Get user's cash
    cash = db.execute(
        "SELECT cash FROM users WHERE id = ?",
        session["user_id"]
    )[0]["cash"]

    holdings = []
    total_value = cash

    for row in rows:
        symbol = row["symbol"]
        shares = row["shares"]

        # Lookup current stock price
        stock = lookup(symbol)
        name = stock["name"]
        price = stock["price"]
        value = price * shares
        total_value += value

        # Get how much user spent on this stock
        cost_data = db.execute(
            "SELECT SUM(shares * price) AS total_spent, SUM(shares) AS total_shares \
             FROM portfolio WHERE user_id = ? AND symbol = ?",
            session["user_id"], symbol
        )[0]

        total_spent = cost_data["total_spent"]
        total_shares = cost_data["total_shares"]

        # Avoid division by zero
        if total_shares and total_shares > 0:
            avg_cost = total_spent / total_shares
        else:
            avg_cost = 0

        profit_loss = value - (avg_cost * shares)

        holdings.append({
            "symbol": symbol,
            "name": name,
            "shares": shares,
            "price": price,
            "value": value,
            "avg_cost": avg_cost,
            "profit_loss": profit_loss
        })

    return render_template("index.html", holdings=holdings, cash=cash, total=total_value)

@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")

    symbol = request.form.get("symbol")
    if not symbol:
        return apology("must provide symbol")

    stock = lookup(symbol)
    if stock is None:
        return apology("invalid symbol")

    shares = request.form.get("shares")
    if not shares or not shares.isdigit() or int(shares) <= 0:
        return apology("invalid number of shares")

    shares = int(shares)
    price = stock["price"]
    total_cost = shares * price

    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
    if cash < total_cost:
        return apology("not enough cash")

    db.execute(
        "INSERT INTO portfolio (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
        session["user_id"],
        stock["symbol"],
        shares,
        price,
    )

    db.execute(
        "UPDATE users SET cash = cash - ? WHERE id = ?",
        total_cost,
        session["user_id"],
    )

    db.execute(
    "INSERT INTO transactions (user_id, type, symbol, shares, amount) VALUES (?, 'BUY', ?, ?, ?)",
    session["user_id"], stock["symbol"], shares, total_cost)


    return redirect("/")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    transactions = db.execute(
        "SELECT symbol, shares, price, timestamp FROM portfolio WHERE user_id = ? ORDER BY timestamp DESC",
        session["user_id"]
    )
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "GET":
        return render_template("quote.html")
    else:
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("Must provide a symbol")
        stock = lookup(symbol)
        if stock is None:
            return apology("Invalid symbol")
        return render_template("quoted.html", stock=stock)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    else:
        username = request.form.get("username")
        if not username:
            return apology("Provide a username please")
        password = request.form.get("password")
        if not password:
            return apology("Provide a password please")
        confirmation = request.form.get("confirmation")
        if not confirmation:
            return apology("Confirm your password please")
        if password != confirmation:
            return apology("Confirm password is not the same as password")
        check_username = db.execute("SELECT * FROM users WHERE username = ?", username)
        if len(check_username) > 0:
            return apology("username already taken")
        """Register user"""
        # hash the password
        hash = generate_password_hash(password)
        # insert the username and the hashed password into the database
        db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hash)
        # redirect the user to the login page
        return redirect("/login")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "GET":
        stocks = db.execute(
            "SELECT symbol, SUM(shares) AS total_shares FROM portfolio WHERE user_id = ? GROUP BY symbol HAVING total_shares > 0",
            session["user_id"],
        )
        return render_template("sell.html", stocks=stocks)

    symbol = request.form.get("symbol")
    if not symbol:
        return apology("must choose a stock")

    shares = request.form.get("shares")
    if not shares or not shares.isdigit() or int(shares) <= 0:
        return apology("invalid number of shares")

    shares = int(shares)

    owned = db.execute(
        "SELECT SUM(shares) AS total FROM portfolio WHERE user_id = ? AND symbol = ?",
        session["user_id"],
        symbol,
    )[0]["total"]

    if owned is None or owned < shares:
        return apology("not enough shares")

    stock = lookup(symbol)
    if stock is None:
        return apology("invalid stock symbol")

    price = stock["price"]
    total_value = shares * price

    db.execute(
        "INSERT INTO portfolio (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
        session["user_id"],
        symbol,
        -shares,
        price,
    )

    db.execute(
        "UPDATE users SET cash = cash + ? WHERE id = ?",
        total_value,
        session["user_id"],
    )
    db.execute(
    "INSERT INTO transactions (user_id, type, symbol, shares, amount) VALUES (?, 'SELL', ?, ?, ?)",
    session["user_id"], symbol, -shares, total_value
    )


    return redirect("/")

@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    """Add cash to user's account"""

    if request.method == "GET":
        return render_template("deposit.html")

    amount = request.form.get("amount")

    # Validate input
    if not amount or not amount.replace(".", "", 1).isdigit():
        return apology("invalid amount")

    amount = float(amount)
    if amount <= 0:
        return apology("amount must be positive")

    # Update user's cash
    db.execute(
        "UPDATE users SET cash = cash + ? WHERE id = ?",
        amount,
        session["user_id"]
    )
    db.execute(
    "INSERT INTO transactions (user_id, type, amount) VALUES (?, 'DEPOSIT', ?)",
    session["user_id"], amount
    )


    return redirect("/")

@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    if request.method == "GET":
        return render_template("withdraw.html")

    amount = request.form.get("amount")

    if not amount or float(amount) <= 0:
        return apology("invalid amount")

    amount = float(amount)

    # Check user's current cash
    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

    if amount > cash:
        return apology("not enough cash")

    # Subtract the amount
    db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", amount, session["user_id"])

    db.execute(
    "INSERT INTO transactions (user_id, type, amount) VALUES (?, 'WITHDRAW', ?)",
    session["user_id"], amount
    )

    return redirect("/")


@app.route("/transactions")
@login_required
def transactions():
    rows = db.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY timestamp DESC",
        session["user_id"]
    )
    return render_template("transactions.html", transactions=rows)

@app.route("/edit", methods=["GET", "POST"])
@login_required
def edit():
    if request.method == "GET":
        return render_template("edit.html")

    # Get form data
    current = request.form.get("current")
    new = request.form.get("new")
    confirmation = request.form.get("confirmation")

    # Validate fields
    if not current or not new or not confirmation:
        return apology("all fields required")

    # Get the user's stored hash
    user = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])[0]

    # Check current password
    if not check_password_hash(user["hash"], current):
        return apology("wrong current password")

    # Check new passwords match
    if new != confirmation:
        return apology("passwords do not match")

    # Update to new hash
    new_hash = generate_password_hash(new)
    db.execute("UPDATE users SET hash = ? WHERE id = ?", new_hash, session["user_id"])

    flash("Password changed!")
    return redirect("/")

@app.route("/chart", methods=["GET", "POST"])
@login_required
def chart():
    if request.method == "GET":
        return render_template("chart.html")

    # POST
    symbol = request.form.get("symbol")
    stock = lookup(symbol)

    if stock is None:
        return apology("invalid symbol")

    # Simulate historical prices
    import random

    prices = []
    base = stock["price"]

    for i in range(30):  # 30 days
        change = random.uniform(-1, 1)
        base += change
        prices.append(round(base, 2))

    return render_template(
        "chart.html",
        symbol=symbol.upper(),
        prices=prices,
    )
@app.route("/download/csv")
@login_required
def download_csv():
    user_id = session["user_id"]

    rows = db.execute("""SELECT symbol, shares FROM portfolio WHERE user_id = ?""", user_id)

    output = "Symbol,Shares\n"
    for row in rows:
        output += f"{row['symbol']},{row['shares']}\n"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=portfolio.csv"}
    )


@app.route("/price")
def price():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "missing symbol"}), 400

    data = lookup(symbol)
    if not data or data.get("price") is None:
        return jsonify({"error": "no price found"}), 404

    try:
        price = float(data["price"])
    except Exception:
        return jsonify({"error": "invalid price"}), 500

    return jsonify({"price": price})
