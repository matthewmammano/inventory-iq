# Inventory IQ - Smart Inventory Management

Flask-based inventory management system with Bayesian prediction, barcode scanning, and automated alerts. Production-ready for Railway deployment.

## Features

- **Smart Predictions**: Bayesian ML for restock forecasting  
- **Barcode Scanning**: QR/barcode item tracking
- **Automated Alerts**: Email notifications for low stock
- **Multi-User**: Role-based access (admin/guest)
- **Location Tracking**: Multi-location inventory management
- **Real-time Reporting**: Usage analytics and history

## Quick Start

### Local Development
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python run.py
```

### Production (Railway)
1. Connect Railway to your repo
2. Set environment variables: `SECRET_KEY`, `DATABASE_URL`, mail settings
3. Deploy automatically via `railpack.json`

## Management Scripts

```bash
python -m scripts.edit_users      # Manage users
python -m scripts.edit_items      # Manage inventory items  
python -m scripts.edit_locations  # Manage locations
python -m scripts.edit_tags       # Manage item tags
```

## Architecture

- **Flask**: Web framework with blueprints
- **SQLAlchemy**: Database ORM with PostgreSQL/SQLite
- **Scikit-learn**: Bayesian prediction models
- **Flask-Login**: Authentication system
- **Gunicorn**: Production WSGI server

## Configuration

- Dev: SQLite database, debug mode
- Prod: PostgreSQL, optimized connection pooling, HTTPS cookies

---
**Author:** Matthew Mammano | mattmammanoweb@gmail.com
