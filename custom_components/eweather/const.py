"""Constants for eweather."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

# Integration metadata
DOMAIN = "eweather"
ATTRIBUTION = "Data provided by the eweather app (eweatherapp.com)"

# Platform parallel updates - applied to all platforms
PARALLEL_UPDATES = 1

# --- Firebase backend (recovered from static APK analysis; see docs/API_CONTRACT.md) ---
# The Android API key is not a secret: it identifies the Firebase project. Reads are
# gated by Firebase Security Rules plus the signed-in user's ID token.
FIREBASE_API_KEY = "AIzaSyAWiIO_KEeAyBDhwu6wfnQ8cgM--RJhKPg"
FIREBASE_PROJECT_ID = "e-weather-api"

# Firebase Auth (email/password) + secure-token refresh REST endpoints.
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# Cloud Firestore REST base for the default database.
FIRESTORE_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

# Firestore collections and fields (CONFIRMED via live probe; see docs/API_CONTRACT.md).
POST_COLLECTION = "Post"
USER_COLLECTION = "User"

# Post fields.
POST_SENDER_FIELD = "sender"  # author uid (string)
POST_TIMESTAMP_FIELD = "created"  # ISO-8601 string; newest-first sort key

# User fields used to identify official (admin) authors.
USER_ADMIN_FIELD = "admin"  # boolean: True => official eweather account
USER_NAME_FIELD = "name"

# How many recent posts to scan per poll. We fetch the newest posts (single-field
# order-by, no composite index needed) and keep the official ones client-side.
DEFAULT_FETCH_LIMIT = 150
# Cache the official-author uid set this long (admin status changes rarely).
ADMIN_CACHE_TTL_SECONDS = 6 * 60 * 60

# --- Configuration / options ---
CONF_POST_COUNT = "post_count"
CONF_OFFICIAL_ONLY = "official_only"
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
CONF_ENABLE_DEBUGGING = "enable_debugging"

# Default configuration values
DEFAULT_UPDATE_INTERVAL_HOURS = 1
DEFAULT_ENABLE_DEBUGGING = False
DEFAULT_POST_COUNT = 10
DEFAULT_OFFICIAL_ONLY = True
