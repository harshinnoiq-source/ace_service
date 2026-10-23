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

    value = value.strip()

    if not re.match(r'^\+?[\d\s\-\(\)]+$', value):
        raise ValidationError(
            "Phone number can only contain digits, spaces, dashes, parentheses, and a leading +."
        )

    has_plus = value.startswith('+')
    digits = re.sub(r'\D', '', value)

    if len(digits) < 7 or len(digits) > 15:
        raise ValidationError("Phone number must contain between 7 and 15 digits.")

    # International number (+ and a country code other than 91)
    if has_plus and not digits.startswith('91'):
        if digits.startswith('0'):
            raise ValidationError("Enter a valid international number with country code.")
        return

    # Indian number
    if has_plus or (len(digits) == 12 and digits.startswith('91')):
        national = digits[2:]
    else:
        national = digits

    if not re.fullmatch(r'[6-9]\d{9}', national):
        raise ValidationError("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")

    if len(set(national)) == 1:
        raise ValidationError("Phone number is not valid.")
def _normalize_number(value):
    value = value.strip()
    has_plus = value.startswith('+')
    digits = re.sub(r'\D', '', value)
    if not digits:
        return value
    return f"+{digits}" if has_plus else digits

def validate_emergency_contact_number(value, own_mobile=None):
    raw = (value or '').strip()
    if not raw:
        return None

    normalized = _normalize_number(raw)
    validate_phone_number(normalized)
    digits = re.sub(r'\D', '', normalized)

    if normalized.startswith('+') and not normalized.startswith('+91'):
        # International number: E.164 allows up to 15 digits, and the country code can't start with 0
        if digits.startswith('0') or not (8 <= len(digits) <= 15):
            raise ValidationError("Enter a valid international number with country code.")
    else:
        national = digits[2:] if (len(digits) == 12 and digits.startswith('91')) else digits
        if not re.fullmatch(r'[6-9]\d{9}', national):
            raise ValidationError("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")
        if len(set(national)) == 1:
            raise ValidationError("Emergency contact number is not valid.")

    if own_mobile and normalized == own_mobile:
        raise ValidationError("Emergency contact number cannot be your own mobile number.")

    return normalized