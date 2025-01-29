from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
from bson.errors import InvalidId
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24) 

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Proszę się zalogować, aby uzyskać dostęp."

# Połączenie z MongoDB
client = MongoClient("mongodb+srv://user123:user123@cluster0.pu9yy.mongodb.net/")
db = client["journey_database"]
journeys_collection = db["journeys"]
passengers_collection = db["passengers"]
checklist_collection = db["checklist"]
users_collection = db["users"]

# Inicjalizacja domyślnej checklisty (jeśli nie istnieje w bazie)
if checklist_collection.count_documents({}) == 0:
    checklist_collection.insert_many([
        {"item": "Poziom paliwa", "status": False},
        {"item": "Sprawność silnika", "status": False},
        {"item": "Kamizelki ratunkowe", "status": False}
    ])

def sync_global_passengers():
    # Pobierz wszystkich pasażerów przypisanych do podróży
    journey_passengers = {
        passenger["name"]: passenger
        for journey in journeys_collection.find()
        for passenger in journey.get("passengers", [])
    }

    # Pobierz ręcznie dodanych pasażerów
    manual_passengers = {
        passenger["name"]: passenger
        for passenger in passengers_collection.find()
        if passenger["name"] not in journey_passengers
    }

    # Połącz listy pasażerów
    combined_passengers = list(journey_passengers.values()) + list(manual_passengers.values())

    # Aktualizuj kolekcję pasażerów
    passengers_collection.delete_many({})
    passengers_collection.insert_many(combined_passengers)

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

    @property
    def is_admin(self):
        return self.role == "admin"

    @staticmethod
    def get(user_id):
        user_data = db["users"].find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(
                id=str(user_data['_id']),
                username=user_data['username'],
                role=user_data.get('role', 'user')  # Domyślnie 'user'
            )
        return None

@login_manager.user_loader
def load_user(user_id):
    user = db["users"].find_one({"_id": ObjectId(user_id)})
    if user:
        return User(str(user["_id"]), user["username"], user["role"])
    return None


@app.route('/')
def home():
    journeys = list(journeys_collection.find())
    return render_template('index.html', journeys=journeys)

@app.route('/add_journey', methods=['GET', 'POST'])
@login_required
def add_journey():
    if request.method == 'POST':
        new_journey = {}

        if departure_time := request.form.get("departure_time"):
            new_journey["departure_time"] = departure_time
        if arrival_time := request.form.get("arrival_time"):
            new_journey["arrival_time"] = arrival_time
        if departure_port := request.form.get("departure_port"):
            new_journey["departure_port"] = departure_port
        if arrival_port := request.form.get("arrival_port"):
            new_journey["arrival_port"] = arrival_port
        if weather := request.form.get("weather"):
            new_journey["weather"] = weather
        
        # Dodanie domyślnej checklisty
        new_journey["checklist"] = [
            {"item": "Poziom paliwa", "status": False},
            {"item": "Sprawność silnika", "status": False},
            {"item": "Kamizelki ratunkowe", "status": False}
        ]

        # Dodanie informacji o użytkowniku
        new_journey["created_by"] = {
            "user_id": current_user.id,
            "username": current_user.username
        }

        journeys_collection.insert_one(new_journey)
        return redirect(url_for('home'))

    return render_template('add_journey.html')

@app.route('/checklist/<journey_id>', methods=['GET', 'POST'])
@login_required
def checklist(journey_id):

    # Sprawdź poprawność journey_id
    try:
        journey_object_id = ObjectId(journey_id)
    except InvalidId:
        return "Invalid journey ID", 400

    # Pobierz podróż z bazy danych
    journey = journeys_collection.find_one({"_id": journey_object_id})
    if not journey:
        return "Journey not found", 404

    if request.method == 'POST':
        # Aktualizuj checklistę dla tej podróży
        updated_checklist = []
        for item in journey.get("checklist", []):
            item_status = request.form.get(item["item"], "off") == "on"
            updated_checklist.append({"item": item["item"], "status": item_status})

        # Zapisz zaktualizowaną checklistę w bazie danych
        journeys_collection.update_one(
            {"_id": journey_object_id},
            {"$set": {"checklist": updated_checklist}}
        )
        return redirect(url_for('checklist', journey_id=journey_id))

    # Pobierz checklistę do wyświetlenia
    checklist_items = journey.get("checklist", [])
    return render_template('checklist.html', checklist=checklist_items, journey_id=journey_id)

@app.route('/report/<journey_id>', methods=['GET', 'POST'])
@login_required
def report(journey_id):
    try:
        journey_object_id = ObjectId(journey_id)
    except InvalidId:
        return "Invalid journey ID", 400

    journey = journeys_collection.find_one({"_id": journey_object_id})
    if not journey:
        return "Journey not found", 404

    # Pobranie danych użytkownika, który utworzył podróż
    creator = journey.get("created_by")
    if creator:
        user_data = db["users"].find_one({"_id": ObjectId(creator["user_id"])})
        if user_data:
            creator["first_name"] = user_data.get("first_name", "")
            creator["last_name"] = user_data.get("last_name", "")

    # Obliczenie liczby dzieci i dorosłych
    passengers = journey.get("passengers", [])
    children = sum(1 for passenger in passengers if passenger["age"] < 18)
    adults = len(passengers) - children

    # Obsługa dodawania notatek
    if request.method == 'POST':
        note_content = request.form.get("note")
        if note_content:
            new_note = {
                "content": note_content,
                "timestamp": datetime.now()
            }
            journeys_collection.update_one(
                {"_id": journey_object_id},
                {"$push": {"notes": new_note}}
            )
            journey.setdefault("notes", []).append(new_note)

    return render_template('report.html', journey=journey, creator=creator, children=children, adults=adults)

@app.route('/edit_passengers/<journey_id>', methods=['GET', 'POST'])
@login_required
def edit_passengers(journey_id):
    try:
        # Konwersja journey_id na ObjectId
        journey_object_id = ObjectId(journey_id)
    except InvalidId:
        return "Invalid journey ID", 400  # Błąd 400: Nieprawidłowy identyfikator

    # Pobierz podróż z bazy danych
    journey = journeys_collection.find_one({"_id": journey_object_id})
    if not journey:
        return "Journey not found", 404  # Błąd 404: Nie znaleziono podróży

    if request.method == 'POST':
        new_names = request.form.getlist('passenger_name')
        new_ages = request.form.getlist('passenger_age')

        updated_passengers = [
            {"name": name, "age": int(age) if age.isdigit() else 0}
            for name, age in zip(new_names, new_ages) if name
        ]
        # Zaktualizuj pasażerów w podróży
        journeys_collection.update_one(
            {"_id": journey_object_id},
            {"$set": {"passengers": updated_passengers}}
        )
        return redirect(url_for('home'))

    return render_template('edit_passengers.html', journey=journey, journey_id=journey_id)

@app.route('/edit_journey/<journey_id>', methods=['GET', 'POST'])
@login_required
def edit_journey(journey_id):
    try:
        journey_object_id = ObjectId(journey_id)
    except InvalidId:
        return "Invalid journey ID", 400

    journey = journeys_collection.find_one({"_id": journey_object_id})
    if not journey:
        return "Journey not found", 404

    if request.method == 'POST':
        updated_data = {}

        # Dodajemy dane tylko, jeśli zostały podane
        if departure_time := request.form.get("departure_time"):
            updated_data["departure_time"] = departure_time
        if arrival_time := request.form.get("arrival_time"):
            updated_data["arrival_time"] = arrival_time
        if departure_port := request.form.get("departure_port"):
            updated_data["departure_port"] = departure_port
        if arrival_port := request.form.get("arrival_port"):
            updated_data["arrival_port"] = arrival_port
        if weather := request.form.get("weather"):
            updated_data["weather"] = weather

        if updated_data:
            journeys_collection.update_one({"_id": journey_object_id}, {"$set": updated_data})

        return redirect(url_for('home'))

    return render_template('edit_journey.html', journey=journey)

@app.route('/delete_journey/<journey_id>', methods=['POST'])
@login_required
def delete_journey(journey_id):
    if not current_user.is_admin:  # Sprawdzamy, czy użytkownik ma rolę admina
        flash("Nie masz uprawnień do usuwania rejsów.", "error")
        return redirect(url_for('home'))

    journeys_collection.delete_one({'_id': ObjectId(journey_id)})
    flash("Rejs został usunięty.", "success")
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users_collection.find_one({"username": username})
        if user and bcrypt.check_password_hash(user["password"], password):
            user_obj = User(str(user["_id"]), user["username"], user["role"])
            login_user(user_obj)
            return redirect(url_for('home'))
        else:
            return "Błędna nazwa użytkownika lub hasło", 401

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        username = request.form.get('username')
        password = request.form.get('password')

        if not (first_name and last_name and username and password):
            flash("Wszystkie pola są wymagane.", "error")
            return redirect(url_for('register'))

        # Sprawdź, czy użytkownik już istnieje
        existing_user = users_collection.find_one({"username": username})
        if existing_user:
            flash("Użytkownik o podanej nazwie już istnieje.", "error")
            return redirect(url_for('register'))

        # Hashowanie hasła
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Zapisz nowego użytkownika w bazie danych
        users_collection.insert_one({
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "password": hashed_password,
            "role": "user"  # Domyślna rola
        })

        flash("Rejestracja zakończona sukcesem. Możesz się teraz zalogować.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        return "Brak dostępu", 403
    return "Panel administracyjny"

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
