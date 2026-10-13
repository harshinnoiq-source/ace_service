"""
Custom password validators for CGM Service.

Enforces:
- 8-20 characters long
- At least one uppercase letter
- At least one lowercase letter
- At least one number
- At least one special character

Registered in settings.py under AUTH_PASSWORD_VALIDATORS.
"""

import re
from django.core.exceptions import ValidationError


class ComplexPasswordValidator:
    """
    Validates that a password meets complexity requirements:
    uppercase, lowercase, number, special character, and length 8-20.
    """

    MIN_LENGTH = 8
    MAX_LENGTH = 20
    SPECIAL_CHARS = r'!@#$%^&*(),.?":{}|<>_\-\[\]\\/~`+=;\''

    def validate(self, password, user=None):
        errors = []

        if len(password) < self.MIN_LENGTH or len(password) > self.MAX_LENGTH:
            errors.append(
                f"Password must be between {self.MIN_LENGTH} and {self.MAX_LENGTH} characters long."
            )

        if not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter.")

        if not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter.")

        if not re.search(r'\d', password):
            errors.append("Password must contain at least one number.")

        if not re.search(f'[{re.escape(self.SPECIAL_CHARS)}]', password):
            errors.append("Password must contain at least one special character.")

        if errors:
            raise ValidationError(errors, code='password_complexity')

    def get_help_text(self):
        return (
            f"Your password must be {self.MIN_LENGTH}-{self.MAX_LENGTH} characters long and include "
            "at least one uppercase letter, one lowercase letter, one number, "
            "and one special character."
        )

def validate_phone_number(value):
    if not value:
        return
    if not re.match(r'^[\d\s\-\(\)\+]+$', value):
        raise ValidationError(
            "Phone number can only contain digits,spaces,dashes,parentheses, and leading +."
        )
    digits_only=re.sub(r'\D','',value)
    if len(digits_only) < 7 or len(digits_only) > 15:
        raise ValidationError(
            "Phone number must contain between 7 and 15 digits."
        )

