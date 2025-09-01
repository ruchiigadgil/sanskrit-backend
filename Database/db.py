from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    try:
        mongo_uri = os.getenv("MONGODB_URI")
        if not mongo_uri:
            raise Exception("MONGODB_URI not set in environment variables")
        client = MongoClient(mongo_uri)
        db = client["sanskrit_learning"]
        return db
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        raise

def initialize_database():
    try:
        db = get_db_connection()
        db.users.create_index("email", unique=True)
        print("Database initialized successfully")
    except Exception as e:
        print(f"Error initializing database: {str(e)}")

def test_connection():
    try:
        db = get_db_connection()
        db.command("ping")
        print("MongoDB Atlas connection successful!")
        print("Collections:", db.list_collection_names())
    except Exception as e:
        print(f"Connection test failed: {str(e)}")

if __name__ == "__main__":
    initialize_database()
    test_connection()