"""Parse #include directives from a header file."""

import re
from pathlib import Path


def parse_includes(header_path: Path) -> list[str]:
    """Extract all #include directives from a header file.

    Args:
        header_path: Path to the header file to parse.

    Returns:
        List of included header names (without angle brackets or quotes).
    """
    includes = []
    include_pattern = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]')

    with open(header_path) as f:
        for line in f:
            match = include_pattern.match(line)
            if match:
                includes.append(match.group(1))

    return includes
