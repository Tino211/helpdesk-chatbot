import datetime
import os
import random
import requests
import mysql.connector
from flask import Flask, request

app = Flask(__name__)

# Load environment variables
WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')

# In-memory user state
user_states = {}

# Database connection function
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="sticketsdb"
    )

# Function to send WhatsApp messages
def send_message(to, text):
    url = f'https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages'
    headers = {
        'Authorization': f'Bearer {WHATSAPP_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
        'messaging_product': 'whatsapp',
        'to': to,
        'text': {'body': text}
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        print("Message sent:", response.json())
    except requests.exceptions.HTTPError as err:
        if err.response:
            print("Error sending message:", err.response.json())
            print("Status code:", err.response.status_code)
        else:
            print("Error sending message:", str(err))

# Function to get categories from the database
def get_categories():
    db = connect_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tblcategory")
    categories = cursor.fetchall()
    cursor.close()
    db.close()
    return categories

# Function to check if the issue is in the knowledge base
def check_knowledge_base(category_name):
    db = connect_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT description FROM tblknowledgebase WHERE categoryName = %s", (category_name,))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result['description'] if result else None

# Function to create a ticket
def create_ticket(full_name, email, category):
    ticket_number = random.randint(1000, 9999)  # Generate a random ticket number
    creation_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db = connect_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO tbltickets (ticketNo, fullName, email, ticketCategory, ticketStatus, creationDate) VALUES (%s, %s, %s, %s, %s, %s)",
                   (ticket_number, full_name, email, category, 'opened', creation_date))
    db.commit()
    cursor.close()
    db.close()
    return ticket_number

# Webhook Endpoint (for WhatsApp messages)
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Received data:", data)

    if 'object' in data:
        message = data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('messages', [{}])[0]
        if message:
            sender = message['from']
            text = message.get('text', {}).get('body', '').strip().lower()

            print(f"Received message from {sender}: {text}")

            # Initialize user state if not present
            if sender not in user_states:
                user_states[sender] = {"step": 0}

            step = user_states[sender]["step"]
            print(f"Current step for {sender}: {step}")

            # Handle user input based on the current step
            if step == 0:
                if "help" in text:
                    send_message(sender, "Hi there! To get help, please enter the department you work in at PSC.")
                    user_states[sender]["step"] = 1
                else:
                    send_message(sender, "Please enter the correct word for me to communicate with you.")

            elif step == 1:
                send_message(sender, "Please select a problem category.")
                categories = get_categories()
                print("Available categories:", categories)
                if categories:
                    buttons = "\n".join([f"{i+1}. {category['categoryName']}" for i, category in enumerate(categories)])
                    send_message(sender, f"Available categories:\n{buttons}")
                else:
                    send_message(sender, "No categories available.")
                user_states[sender]["step"] = 2

            elif step == 2:
                categories = get_categories()  # Fetch categories again to ensure we have the latest
                if text.isdigit() and 1 <= int(text) <= len(categories):
                    category = categories[int(text) - 1]['categoryName']
                    send_message(sender, f"Can you specify the exact problem you have with {category}?")
                    user_states[sender]["selected_category"] = category  # Store selected category for later use
                    user_states[sender]["step"] = 3
                else:
                    send_message(sender, "Please select a valid category number.")

            elif step == 3:
                # Check the issue against the knowledge base using the selected category
                category_name = user_states[sender]["selected_category"]
                response = check_knowledge_base(category_name)
                if response:
                    send_message(sender, f"Knowledge Base Response: {response}")
                    send_message(sender, "Did this help you? (Reply with 'yes' or 'no')")
                    user_states[sender]["step"] = 6  # Move to the next step for help confirmation
                else:
                    send_message(sender, "No information found for your issue. Please create a ticket for your issue by typing your full_name & email eg tinotenda_katso, 123@gmail.com.")
                    user_states[sender]["step"] = 4  # Move to next step for ticket creation

            elif step == 4 and '@' in text and len(text) > 5:
                full_name = text  # Assuming the user will enter their full name in the next message
                user_states[sender]["full_name"] = full_name
                send_message(sender, "Please enter your email address.")
                user_states[sender]["step"] = 5

            elif step == 5 and '@' in text and len(text) > 5:
                email = text
                full_name = user_states[sender].get("full_name", "")
                category = user_states[sender]["selected_category"]  # Get the previously selected category
                ticket_number = create_ticket(full_name, email, category)
                send_message(sender, f"Ticket created successfully!\nName: {full_name}\nTicket No: {ticket_number}\nStatus: opened\nEmail ID: {email}\nKindly wait for a response from the responsible IT personnel within 24 hours.")
                user_states.pop(sender)  # Clear user state after ticket creation

            elif step == 6:
                if "yes" in text:
                    send_message(sender, "My pleasure!")
                    user_states.pop(sender)  # Clear user state if helped
                elif "no" in text:
                    send_message(sender, "Please create a ticket so that the responsible IT personnel may take a look at it. Enter your full name and email.")
                    user_states[sender]["step"] = 4  # Go back to ticket creation steps
                else:
                    send_message(sender, "Please reply with 'yes' or 'no'.")

    return '', 200

# Webhook Verification (Required by WhatsApp API)
@app.route('/webhook', methods=['GET'])
def verify_webhook():
    if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return 'Forbidden', 403

# Start Server
if __name__ == '__main__':
    app.run(port=int(os.getenv('PORT', 8000)), debug=True)