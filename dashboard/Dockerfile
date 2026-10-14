# Vigia back-office: Django served by Gunicorn, static files by WhiteNoise
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Gather admin and app static files into STATIC_ROOT at build time.
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8001
# Apply Django's own migrations (auth, sessions, admin), then serve.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8001 --workers 2 --access-logfile -"]
