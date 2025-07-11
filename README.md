# Inventory Management System - Setup Guide

This README provides instructions on how to set up and use the Inventory Management System, including the new management scripts for editing user information, tags, locations, and alerts.

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

## Running the Management Scripts

### Purpose
The following scripts allow you to manage various aspects of the inventory system, including user details, tags, locations, and alerts.

### Steps to Run

1. **Navigate to the Project Directory:**
    Make sure you're in the root directory of the project (where the `app/`, `scripts/`, and other directories reside).
    ```bash
    cd /path/to/your/inventory-iq
    ```

2. **Run the Scripts:**
    You can run the following scripts using the terminal, as described below.

    - **Manage Alerts:**
        To manage user alerts, use:
        ```bash
        python -m scripts.edit_alerts
        ```

    - **Manage Locations:**
        To manage user locations, use:
        ```bash
        python -m scripts.edit_locations
        ```

    - **Edit Users:**
        To manage user information (add or delete users), use:
        ```bash
        python -m scripts.edit_users
        ```

3. **Follow the Prompts:**
    Each script will prompt you to interact with the system. The prompts will vary based on the script, allowing you to:

    - **Add** new entries (alerts, locations, users).
    - **Delete** existing entries.
    - **View** current entries.

    **Example commands for each script:**

    - **Add a new alert for a user:**
        ```bash
        Enter user email to manage alerts: user@example.com
        Enter the details for the new alert...
        ```

    - **Add a new location for a user:**
        ```bash
        Enter user email to manage locations: user@example.com
        Enter the location name...
        ```

    - **Add a new user to the system:**
        ```bash
        Enter the user details (email, display name, PIN, etc.)...
        ```

### Notes

- **Script Functions:** Each script is self-contained, and performs specific tasks related to managing user data, tags, locations, or alerts.
- **App Context:** All scripts expect to be run within a Flask app context. If you encounter issues related to database connections, ensure your Flask app is properly configured with the required environment variables.
- **Exit or Cancel:** You can always exit or cancel operations within the scripts by entering `q` when prompted.

## Troubleshooting
* **ModuleNotFoundError:**
    If you encounter `ModuleNotFoundError`:
    * Make sure you’ve installed all required dependencies by running `pip install -r requirements.txt`.
    * Ensure you’re running the script from the correct directory.

* **Database Issues:**
    If you encounter issues with the database, make sure the Flask app is configured to access the SQLite databases correctly (`users.db` and `squads/<username>.db`).

## Conclusion
Running these management scripts will allow you to manage user-related data, tags, locations, and alerts independently for each squad, providing flexible control over the inventory system's configuration.

For additional help or customizations, please reach out to the development team.

---
**Prepared by:**
Matthew Mammano

*Email:* mattmammanoweb@gmail.com
*Location:* Point Pleasant, NJ
