# Code Standards & Best Practices for Production

## Philosophy: KISS + DRY = Production Ready

**KISS (Keep It Simple, Stupid):** Write the simplest code that solves the problem. Complexity = bugs.
**DRY (Don't Repeat Yourself):** One source of truth for each piece of logic.
**Explicit is better than implicit:** Clear code > clever code (per Zen of Python).

---

## Core Principles - Order of Priority

1. **Readability** - Code is read 100x more than written. Write for humans first.
2. **Simplicity** - Shortest viable solution. No premature optimization.
3. **Reliability** - Proper error handling, logging, configuration.
4. **Maintainability** - Easy to debug, modify, and extend 6 months later.
5. **Performance** - Only optimize after profiling and measuring.

---

## Configuration & Constants

**Golden Rule:** ZERO hardcoded values. All configs in one place, environment-driven.

```python
# config.py - Single source of truth
import os

class Config:
    DEBUG = os.getenv("FLASK_ENV") == "dev"
    DATABASE_URL = os.getenv("DATABASE_URL")
    SECRET_KEY = os.getenv("SECRET_KEY")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", 10))

# Use in code
from config import Config
db_url = Config.DATABASE_URL  # Not os.environ.get(...) all over the place
```

**Benefits:** Change deployment without touching code. Easy testing. Secure in prod.

---

## Module Organization - Keep Files SHORT

```
app/
├── models.py           # Only data models (max 300 lines)
├── routes.py           # Only Flask routes/views (max 200 lines)
├── services.py         # Business logic, extracted from routes
├── db.py               # Database setup (max 50 lines)
├── config.py           # All config constants
└── utils/
    ├── validators.py   # Input validation
    └── decorators.py   # Reusable decorators
```

**Per-file limit:** Max ~200-300 lines. If longer, split it.
**Per-function limit:** Max 20 lines. Use helper functions.

---

## Function Design - Shallow Call Depth

```python
# ❌ BAD: Deep nesting, hard to follow
def process_order(order_id):
    order = get_order(order_id)
    if order:
        customer = get_customer(order.customer_id)
        if customer:
            if customer.credit_score > 700:
                items = get_items(order.item_ids)
                # ... 50 more lines of nested logic

# ✅ GOOD: Flat, explicit, easy to test and debug
def process_order(order_id: int) -> bool:
    order = get_order(order_id)
    if not order:
        return False

    if not validate_customer(order.customer_id):
        return False

    process_items(order.item_ids)
    return True
```

**Rules:**
- Max 1-2 levels of nesting. Use early returns to flatten.
- Extract nested logic into separate functions.
- Each function = one job. No "god functions."

## Type Hints - Make Them Your Best Friend

```python
# Modern Python 3.10+ syntax - ALWAYS use this
from typing import Optional

def fetch_user(user_id: int) -> User | None:
    """Fetch user by ID, return None if not found."""
    return db.query(User).get(user_id)

def process_batch(items: list[dict]) -> dict[str, int]:
    """Process items, return counts by status."""
    return {"success": 10, "failed": 2}
```

**Why it matters:**
- IDE auto-complete works (huge productivity boost)
- Catches bugs before runtime
- Self-documents code
- Tools like Pylance detect errors instantly

**Never:** `def foo(x):` or `x: Any` or `-> Any`
**Always:** Be specific: `int`, `str`, `list[str]`, `User | None`

---

## Error Handling - Fail Fast, Log Everything

```python
from loguru import logger

def process_payment(amount: float, user_id: int) -> bool:
    """Process payment, return success/failure."""

    # Validate early, fail fast
    if amount <= 0:
        logger.warning(f"Invalid amount {amount} for user {user_id}")
        return False

    try:
        charge_user(user_id, amount)
        logger.info(f"Payment processed: user={user_id}, amount={amount}")
        return True
    except PaymentGatewayError as e:
        logger.error(f"Payment failed for user {user_id}: {e}")
        # Don't re-raise unless caller needs to handle it
        return False
    except Exception as e:
        logger.critical(f"Unexpected error processing payment: {e}")
        raise  # Only re-raise if truly unexpected
```

**Rules:**
- Validate inputs immediately (fail fast)
- Use loguru, never print()
- Log at appropriate level (debug, info, warning, error, critical)
- Catch specific exceptions, not bare Exception
- Return False/None instead of raising when expected to fail

---

## Input Validation - Use Pydantic

```python
from pydantic import BaseModel, field_validator, EmailStr

class UserCreate(BaseModel):
    email: EmailStr  # Validates email format
    password: str
    age: int

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be >= 8 chars')
        return v

    @field_validator('age')
    @classmethod
    def validate_age(cls, v: int) -> int:
        if v < 0 or v > 150:
            raise ValueError('Invalid age')
        return v

# In Flask route
@app.post('/users')
def create_user():
    data = UserCreate(**request.json)  # Auto-validates, raises ValidationError if bad
    user = save_user(data)
    return {"id": user.id}, 201
```

**Benefits:** Validation in one place, reusable, type-safe.

---

## Logging - Replace All print() Statements

```python
from loguru import logger
import sys

# Configure once at app startup
logger.remove()  # Remove default handler
logger.add(
    sys.stdout,
    format="<level>{level: <8}</level> | {name}:{function}:{line} - {message}",
    level="INFO"
)
logger.add(
    "logs/app.log",
    rotation="500 MB",  # Auto-rotate at 500MB
    retention="7 days",
    level="DEBUG"
)

# Use everywhere instead of print()
logger.debug("Debug info")          # Dev/testing only
logger.info("User logged in")       # Important events
logger.warning("Low stock alert")   # Needs attention
logger.error("Database error")      # Something failed
logger.critical("Out of memory")    # System critical
```

**Never:** `print(f"User: {user}")`
**Always:** `logger.info(f"User logged in: {user.email}")`

---

## Database - Connection Pooling & Context Managers

```python
# db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    echo=False
)

SessionLocal = sessionmaker(bind=engine)

@contextmanager
def get_session():
    """Context manager for database sessions - prevents leaks."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# Usage - automatic cleanup
def get_user(user_id: int) -> User | None:
    with get_session() as session:
        return session.query(User).get(user_id)
```

**Why:** Automatic cleanup, no connection leaks, exception-safe.



## Git Commits - Conventional Format

```bash
# Good commits
feat(auth): add OAuth2 authentication support
fix(inventory): resolve stock count underflow
refactor(services): extract email logic to service class
docs(api): update endpoint documentation
chore(deps): update Flask to v2.3.0

# Guidelines
# - Imperative mood: "add" not "added"
# - No period at end
# - 50 char max for subject
# - scope in parentheses (optional but recommended)
```

---

## Testing - Write Tests for Complex Logic

```python
# tests/test_user_service.py
import pytest
from app.services import UserService

def test_create_user_success():
    data = UserCreate(email="test@example.com", password="securepass123")
    user = UserService.create(data)
    assert user.id is not None
    assert user.email == "test@example.com"

def test_create_user_duplicate_email():
    UserService.create(UserCreate(email="test@example.com", password="pass1"))

    with pytest.raises(ValueError):
        UserService.create(UserCreate(email="test@example.com", password="pass2"))

def test_get_user_not_found():
    user = UserService.get(9999)
    assert user is None
```

**Write tests for:**
- Business logic (services)
- Edge cases (empty input, invalid data)
- Error conditions (duplicate, not found)

**Skip testing:**
- Database queries (covered by service tests)
- HTTP routing (covered by integration tests)
- Third-party libraries

---

## Docstrings - Short & Clear

```python
def fetch_user(user_id: int) -> User | None:
    """Fetch user by ID, return None if not found."""
    with get_session() as session:
        return session.query(User).get(user_id)

def validate_email(email: str) -> bool:
    """Check if email is valid format."""
    return "@" in email and "." in email.split("@")[1]
```

**Keep docstrings short.** Type hints make long docstrings unnecessary.

---

## Checklist - Before Committing

- [ ] All new functions have type hints (`-> ReturnType`)
- [ ] Input validation with Pydantic or early returns
- [ ] Error handling: try/except or return None
- [ ] Logging instead of print statements
- [ ] No hardcoded values (use config)
- [ ] Functions under 20 lines
- [ ] Files under 300 lines (split if longer)
- [ ] No code duplication (extract to helper)
- [ ] Ruff/Black formatted (run `ruff check --fix . && black .`)
- [ ] Pre-commit hooks pass (`pre-commit run --all-files`)
- [ ] Tests pass for new logic

---

## Important Reminders

- **KISS:** Simplest code that works wins
- **DRY:** Extract helpers at 3+ repeated lines
- **Types:** Always add type hints - IDE magic
- **Logging:** `logger.info()` not `print()`
- **Config:** Never hardcode values
- **Early returns:** Flatten nested code
- **Short functions:** Max 20 lines per function
- **Short files:** Max 300 lines per file
- **Validation:** Check inputs immediately
- **No emojis:** In code, commits, or comments
