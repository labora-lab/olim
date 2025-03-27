#!/bin/sh

# entrypoint.sh

echo "Compiling translations"
uv run pybabel compile -d olim/translations

# Check if database needs upgrading
echo "Checking database state..."
if ! flask --app olim db check 2>&1 | grep -q "No new upgrade operations detected"; then
    echo "Pending migrations detected. Running upgrade..."
    flask --app olim db upgrade
else
    echo "Database is up-to-date!"
fi

# Start main application
exec "$@"