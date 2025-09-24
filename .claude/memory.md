# Code Standards & Best Practices

## Core Principles

### Professional Production Code
- Zero tolerance for hardcoded values - Use config files, environment variables, constants
- Comprehensive error handling - Never let exceptions bubble up unhandled
- Logging over print statements - Use proper logging levels
- Security first - Validate inputs, sanitize outputs, never expose credentials
- Performance awareness - Consider time/space complexity, use appropriate data structures

### DRY (Don't Repeat Yourself)
- Extract common functionality into utilities, helpers, base classes
- Use constants for repeated values
- Create reusable components
- If you write similar code 3+ times, extract it

### Modular Architecture
- Clear separation of concerns
- Good: Separate modules for services, models, utilities
- Bad: All logic in one file

### Organization Standards
```
project/
├── app/
│   ├── models/          # Data models
│   ├── services/        # Business logic
│   ├── utils/           # Helper functions
│   ├── api/             # API endpoints
│   └── tasks/           # Background jobs
├── config/              # Configuration files
├── tests/              # All tests
└── docs/               # Documentation
```

## Type Hinting (MANDATORY)

### Function Signatures
```python
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

def process_user_data(
    user_id: int,
    email: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Union[str, int]]:
    """Process user data with proper type hints."""
    pass
```

### Class Properties
```python
from typing import ClassVar
from dataclasses import dataclass

@dataclass
class User:
    id: int
    email: str
    created_at: datetime
    active: bool = True

    MAX_LOGIN_ATTEMPTS: ClassVar[int] = 5
```

## Documentation Standards

### NumPy Style Docstrings (MANDATORY)
```python
def calculate_user_score(
    user_id: int,
    actions: List[Dict[str, Any]],
    weight_factor: float = 1.0
) -> float:
    """
    Calculate comprehensive user activity score.

    Parameters
    ----------
    user_id : int
        Unique identifier for the user
    actions : List[Dict[str, Any]]
        List of user action dictionaries
    weight_factor : float, optional
        Global multiplier for scores, by default 1.0

    Returns
    -------
    float
        Calculated user score ranging from 0.0 to 100.0

    Raises
    ------
    ValueError
        If user_id is negative or actions list is empty
    """
    pass
```

## Code Quality Standards

### Error Handling
```python
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

@contextmanager
def handle_database_errors():
    """Context manager for database error handling."""
    try:
        yield
    except DatabaseConnectionError as e:
        logger.error(f"Database connection failed: {e}")
        raise ServiceUnavailableError("Database temporarily unavailable")
    except Exception as e:
        logger.critical(f"Unexpected database error: {e}")
        raise InternalServerError("Internal system error")
```

### Input Validation
```python
from pydantic import BaseModel, validator, EmailStr

class UserCreateRequest(BaseModel):
    """Request model for user creation with validation."""

    email: EmailStr
    password: str
    age: int

    @validator('password')
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v
```

## Performance & Resources

### Database Optimization
```python
from sqlalchemy.orm import selectinload

def get_users_with_preferences(db_session: Session) -> List[User]:
    """Efficiently fetch users with preferences using eager loading."""
    return db_session.query(User)\
        .options(selectinload(User.preferences))\
        .all()
```

### Caching Strategy
```python
@cache_manager.cache_result("user_profile", ttl=1800)
def get_user_profile_data(user_id: int) -> Dict[str, Any]:
    """Get user profile with 30-minute caching."""
    return fetch_user_data(user_id)
```

## Security Standards

### Input Sanitization
```python
import bleach

def sanitize_html_input(html_content: str) -> str:
    """Sanitize HTML input to prevent XSS attacks."""
    allowed_tags = ['p', 'br', 'strong', 'em']
    return bleach.clean(html_content, tags=allowed_tags, strip=True)
```

### Authentication & Authorization
```python
from functools import wraps

def require_auth(f: Callable) -> Callable:
    """Decorator to require authentication for endpoint access."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            raise UnauthorizedError("Authentication token required")
        return f(*args, **kwargs)
    return wrapper
```

## Code Formatting & Style

### Import Organization
```python
# Standard library imports
import json
import logging
from datetime import datetime

# Third-party imports
from flask import Flask, request
from pydantic import BaseModel

# Local application imports
from app.models.user import User
from app.services.email import EmailService
```

### Constants and Configuration
```python
# Constants at module level
MAX_RETRY_ATTEMPTS: int = 3
DEFAULT_TIMEOUT: float = 30.0

class DatabaseConfig:
    """Database configuration settings."""
    HOST: str = "localhost"
    PORT: int = 5432
```

## Commit Standards

### Conventional Commits Format
```
type(scope): description

[optional body]
[optional footer]
```

### Commit Types
- **feat**: New feature for the user
- **fix**: Bug fix for the user
- **docs**: Documentation changes
- **style**: Code style changes (formatting, etc.)
- **refactor**: Code refactoring without changing functionality
- **test**: Adding or updating tests
- **chore**: Build process or auxiliary tool changes

### Examples
```bash
feat(auth): add OAuth2 authentication support
fix(auth): resolve token expiration handling
docs(api): update endpoint documentation
refactor(services): extract email service class
test(auth): add unit tests for login flow
chore(deps): update Flask to v2.3.0
```

### Guidelines
- Use imperative mood ("add" not "added")
- Don't capitalize first letter
- Don't end with period
- Limit to 50 characters
- Be clear and concise

## Quick Reference Checklist

### Before Committing Code
- [ ] All functions have NumPy-style docstrings
- [ ] Type hints on all function parameters and returns
- [ ] Input validation implemented
- [ ] Error handling in place
- [ ] No hardcoded values
- [ ] Logging instead of print statements
- [ ] Tests written and passing
- [ ] Code follows DRY principles
- [ ] Security considerations addressed
- [ ] Performance implications considered
- [ ] Conventional commit message format used

### Code Review Checklist
- [ ] Code is self-documenting
- [ ] Functions are single-purpose
- [ ] No code duplication
- [ ] Proper error handling
- [ ] Security vulnerabilities addressed
- [ ] Performance bottlenecks identified
- [ ] Test coverage adequate
- [ ] Documentation up to date

## Important Reminders

- **NEVER use emojis** in code or responses unless explicitly requested
- **Always use type hints** - this is mandatory
- **Keep functions short** and focused on single responsibility
- **Use logging instead of print** statements
- **Validate all inputs** before processing
- **Handle errors gracefully** with proper exception handling
- **Write tests** for all new functionality
- **Follow DRY principles** - extract common code
- **Use meaningful variable names** that explain their purpose
- **Add docstrings** to all functions and classes