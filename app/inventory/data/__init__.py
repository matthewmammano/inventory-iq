"""Database persistence and event-sourced quantity calculations.

Single source of truth for inventory state:
- models.py: SQLAlchemy data definitions (Items, ActionLogs, UserItemLocations)
- item_queries.py: Item CRUD and batch operations
- quantity.py: Event-sourced quantity calculations from ActionLogs (never cached)
- action_log_queries.py: Action history queries for auditing
"""
