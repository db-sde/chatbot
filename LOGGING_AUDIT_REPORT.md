# Logging and Request Visibility Audit Report

This report documents the logging configuration, request flow visibility issues, and exact diagnostic trace paths for the DegreeBaba chatbot platform.

---

## 1. Logging Configuration & Suppression

### Current Setup:
1. **Python Root Logger Configuration:**
   * There is no custom `logging.basicConfig` or `logging.config.dictConfig` defined in the application.
   * By default, Python's root logger is set to the `WARNING` level.
   * This inherits down to our module loggers created via `logger = logging.getLogger(__name__)`.
2. **Uvicorn Access Logger:**
   * Uvicorn configures its own loggers (`uvicorn`, `uvicorn.access`, `uvicorn.error`) explicitly to the `INFO` level.
   * This is why Uvicorn request access logs (e.g. `INFO: 127.0.0.1:65206 - "GET /api/session/history ... 403 Forbidden"`) are printed to stdout, while the application's own `logger.info()` logs are completely suppressed.

---

## 2. Request Interception & Flow Audit

### Do requests reach FastAPI?
* **Yes.** Because Uvicorn access logs print standard HTTP responses (like `403 Forbidden`), the requests are successfully arriving at the Uvicorn ASGI server and hitting FastAPI.
* **CORS Preflight Interception:** For `OPTIONS /chat` preflight requests, the request enters Starlette's [`CORSMiddleware`](file:///Users/aryankinha/Documents/Degree/chatbot/backend/main.py#L46). If the origins list is misconfigured or contains malformed values (such as syntax errors in `ALLOWED_SITE_KEYS`), CORS matches fail, and the preflight request either gets rejected or drops through default routing, causing Uvicorn to report `400 Bad Request` or `405 Method Not Allowed`.

---

## 3. Exact Source of the 403 Forbidden Response

When a `403 Forbidden` response is returned, it originates from one of two specific locations in the python codebase:

1. **Origin Verification Gateway — [`auth.py`](file:///Users/aryankinha/Documents/Degree/chatbot/backend/auth.py#L32):**
   * Raised by `validate_site_request` if the client's `Origin` or `Referer` domain is not listed in settings.
   * *Example Trigger:* Requesting `/api/session/history` with `site_key=default` when the configuration is corrupted, causing the allowed host check to return `False`.
2. **Security IP Geoblocking Check — [`main.py`](file:///Users/aryankinha/Documents/Degree/chatbot/backend/main.py#L139):**
   * Raised inside the `/chat` route if the client's IP is found in the `blocked_ips` table.
   * *Example Trigger:* A blacklisted client attempting to start a new chat turn.

---

## 4. Diagnostics & Middleware Added

To provide full visibility, we have introduced a temporary **`request_diagnostic_middleware`** at the warning level to log all request flows:
* **Request Method**
* **Request Path**
* **Client IP**
* **Response Status Code**

Additional warning-level logging blocks have been added around `/chat` request validation, IP blocks, and security layer execution so they always write to console regardless of logging level.
