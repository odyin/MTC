"""Basic PowerLanguage syntax validation for generated code."""

import re


class ValidationError:
    def __init__(self, line_num: int, message: str):
        self.line_num = line_num
        self.message = message

    def __repr__(self):
        return f"Line {self.line_num}: {self.message}"


def validate_powerlanguage(code: str) -> list[ValidationError]:
    """Run basic syntax checks on PowerLanguage code.

    Returns list of ValidationError. Empty list = valid.
    """
    errors = []
    lines = code.split("\n")

    has_inputs = False
    has_variables = False
    begin_count = 0
    end_count = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("//") or stripped.startswith("{"):
            continue

        if stripped.startswith("Inputs:"):
            has_inputs = True
        if stripped.startswith("Variables:"):
            has_variables = True

        # Count Begin/End blocks
        if re.search(r'\bBegin\b', stripped, re.IGNORECASE):
            begin_count += 1
        if re.search(r'\bEnd\b', stripped, re.IGNORECASE):
            end_count += 1

        # Check for unterminated statements (should end with ; or Begin/End or Then)
        if (not stripped.startswith("[") and
            not stripped.startswith("{") and
            not stripped.endswith(";") and
            not stripped.endswith("Then") and
            not re.search(r'\bBegin\b$', stripped, re.IGNORECASE) and
            not re.search(r'\bEnd;?$', stripped, re.IGNORECASE) and
            not stripped.startswith("//")):
            # This might be a continuation line, only warn
            pass

    # Check matched Begin/End
    if begin_count != end_count:
        errors.append(ValidationError(0, f"Mismatched Begin/End blocks: {begin_count} Begin vs {end_count} End"))

    if not has_inputs:
        errors.append(ValidationError(0, "Missing 'Inputs:' declaration"))

    if not has_variables:
        errors.append(ValidationError(0, "Missing 'Variables:' declaration"))

    return errors
