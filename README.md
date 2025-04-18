# Inventory Management System - Setup Guide

This README provides instructions on how to set up and use the Inventory Management System, specifically focusing on adding a new user using the `add_user.py` script.

## Prerequisites

Before running the setup script, ensure you have the following:

1.  **Python 3.10 or higher** installed on your machine.
2.  **Dependencies** installed from `requirements.txt`. You can install them by running:
    ```bash
    pip install -r requirements.txt
    ```
* **Virtual Environment (recommended but not required):**
    It's recommended to use a virtual environment to isolate the dependencies of this project.
    To create and activate a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use venv\Scripts\activate
    ```
* **Flask App Initialized:**
    Ensure the Flask app is configured properly with the necessary environment variables.
    Make sure your app can connect to the database (`users.db` and `squads/<username>.db`).

## Running the add_user.py Script

### Purpose
This script allows you to add a new user and initialize a new squad's database. You will be prompted to enter the necessary information for the user (such as username, email, image URL, and notes). The script will then create a new user and a new squad database for inventory management.

### Steps to Run
1.  **Navigate to the Project Directory:**
    First, make sure you're in the root directory of the project (where the `app/`, `scripts/`, and other directories reside).
    ```bash
    cd /path/to/your/inventory-iq
    ```
2.  **Run the add_user.py Script:**
    Use the following command to add a new user and initialize their squad database:
    ```bash
    python -m scripts.add_user
    ```
3.  **Input the Required Information:**
    The script will prompt you for the following details:
    * `username`: The unique name for the squad.
    * `email`: The email associated with the squad.
    * `image URL`: The URL of the squad's image or logo.
    * `notes`: Additional details (e.g., contact information, full name of the squad, etc.).

    *Example input:*
    ```yaml
    username: WallEMS
    email: wall@ems.com
    image URL: [http://example.com/image.jpg](http://example.com/image.jpg)
    notes: Contact number: (123) 456-7890
    ```
4.  **User Creation and Squad Database Setup:**
    After entering the details, the script will:
    * Add the user to the `users.db` database.
    * Create a new SQLite database for the squad in the `instance/squads/` directory.
    * Set up the database connection for the squad.
    * Initialize necessary tables for the squad's inventory.

    *Example output:*
    ```bash
    WallEMS added to instance/users.db
    Database created at instance/squads/WallEMS.db
    Done!
    ```

## Notes
* **Squad Database:** Each squad gets its own SQLite database, stored under `instance/squads/`, allowing them to manage their own inventory independently.
* **User Identification:** The script ensures that the squad's username is unique, and checks if the squad exists in the `users.db` before creating a new user entry.
* **Default Timezone:** The script uses `datetime` to handle timestamps, and assumes UTC as the default timezone for squad activity unless specified.
* **Ensure Database Integrity:** After running this script, you can access the new squad's data via Flask and continue configuring other aspects of the inventory management system.

## Troubleshooting
* **ModuleNotFoundError:**
    If you encounter `ModuleNotFoundError`:
    * Make sure you’ve installed all required dependencies by running `pip install -r requirements.txt`.
    * Ensure you’re running the script from the correct directory.
* **Database Issues:**
    If you encounter issues with the database, make sure the Flask app is configured to access the SQLite databases correctly (`users.db` and `squads/<username>.db`).
* **Already Exists:**
    If the script detects that the username already exists in the `users.db` database, it will print the message: `{username} already exists in user.db`.

## Conclusion
Running this script will allow you to quickly add new squad users and initialize their database for managing medical inventory. This approach ensures each squad operates independently, with their own database and system access.

For additional help or customizations, please reach out to the development team.

---
**Prepared by:**
Matthew Mammano

*Email:* mattmammanoweb@gmail.com
*Location:* Point Pleasant, NJ