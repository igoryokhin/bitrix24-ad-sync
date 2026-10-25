#!/usr/bin/env python3
"""Печатает werkzeug-хэш пароля для ADMIN_FALLBACK_PASSWORD_HASH в .env.

Использование:
    python webui/scripts/gen_fallback_hash.py 'МойПароль123!'
"""
import sys

from werkzeug.security import generate_password_hash


def main():
    if len(sys.argv) != 2:
        print("Использование: python gen_fallback_hash.py '<пароль>'", file=sys.stderr)
        sys.exit(1)
    print(generate_password_hash(sys.argv[1]))


if __name__ == "__main__":
    main()
