import traceback

from flask import abort, render_template
from flask_babel import gettext as _

from . import app


def get_traceback_info(error) -> str | None:
    """Extract traceback information from error if available."""
    try:
        if hasattr(error, "original_exception") and error.original_exception:
            # For wrapped exceptions, get the original traceback
            return "".join(
                traceback.format_exception(
                    type(error.original_exception),
                    error.original_exception,
                    error.original_exception.__traceback__,
                )
            )
        elif hasattr(error, "__traceback__") and error.__traceback__:
            # For direct exceptions
            return "".join(traceback.format_exception(type(error), error, error.__traceback__))
        elif app.config.get("DEBUG") and str(error) != error.__class__.__name__:
            # In debug mode, at least show the error string
            return str(error)
    except Exception:
        pass
    return None


@app.errorhandler(400)
def bad_request(error) -> ...:
    """Handle 400 Bad Request errors."""
    return render_template(
        "error.html",
        error_code=400,
        error_title=_("Bad Request"),
        error_message=_(
            "The request could not be understood by the server due to malformed syntax."
        ),
        error_icon="exclamation-triangle-fill",
        error_color="red",
    ), 400


@app.errorhandler(401)
def unauthorized(error) -> ...:
    """Handle 401 Unauthorized errors."""
    return render_template(
        "error.html",
        error_code=401,
        error_title=_("Unauthorized"),
        error_message=_("You need to log in to access this resource."),
        error_icon="shield-exclamation",
        error_color="yellow",
    ), 401


@app.errorhandler(403)
def forbidden(error) -> ...:
    """Handle 403 Forbidden errors."""
    return render_template(
        "error.html",
        error_code=403,
        error_title=_("Access Forbidden"),
        error_message=_("You do not have permission to access this resource."),
        error_icon="shield-exclamation",
        error_color="blue",
    ), 403


@app.errorhandler(404)
def not_found(error) -> ...:
    """Handle 404 Not Found errors."""
    print(404)
    return render_template(
        "error.html",
        error_code=404,
        error_title=_("Page Not Found"),
        error_message=_("The page you are looking for could not be found."),
        error_icon="compass",
        error_color="blue",
    ), 404


@app.errorhandler(405)
def method_not_allowed(error) -> ...:
    """Handle 405 Method Not Allowed errors."""
    return render_template(
        "error.html",
        error_code=405,
        error_title=_("Method Not Allowed"),
        error_message=_("The method used is not allowed for this resource."),
        error_icon="x-circle-fill",
        error_color="red",
    ), 405


@app.errorhandler(408)
def request_timeout(error) -> ...:
    """Handle 408 Request Timeout errors."""
    return render_template(
        "error.html",
        error_code=408,
        error_title=_("Request Timeout"),
        error_message=_("Your request has timed out."),
        error_icon="clock-fill",
        error_color="orange",
        info_color="orange",
    ), 408


@app.errorhandler(413)
def payload_too_large(error) -> ...:
    """Handle 413 Payload Too Large errors."""
    return render_template(
        "error.html",
        error_code=413,
        error_title=_("File Too Large"),
        error_message=_("The file you are trying to upload is too large."),
        error_icon="file-earmark-x",
        error_color="amber",
    ), 413


@app.errorhandler(429)
def too_many_requests(error) -> ...:
    """Handle 429 Too Many Requests errors."""
    return render_template(
        "error.html",
        error_code=429,
        error_title=_("Too Many Requests"),
        error_message=_("You have made too many requests in a short period."),
        error_icon="speedometer2",
        error_color="yellow",
    ), 429


@app.errorhandler(500)
def internal_server_error(error) -> ...:
    """Handle 500 Internal Server Error."""
    return render_template(
        "error.html",
        error_code=500,
        error_title=_("Internal Server Error"),
        error_message=_("An unexpected error occurred on the server."),
        error_icon="gear-wide-connected",
        error_color="red",
        info_color="red",
        show_retry=True,
        traceback_info=get_traceback_info(error),
        error=error,
    ), 500


@app.errorhandler(502)
def bad_gateway(error) -> ...:
    """Handle 502 Bad Gateway errors."""
    return render_template(
        "error.html",
        error_code=502,
        error_title=_("Bad Gateway"),
        error_message=_("The server received an invalid response from an upstream server."),
        error_icon="router-fill",
        error_color="red",
    ), 502


@app.errorhandler(503)
def service_unavailable(error) -> ...:
    """Handle 503 Service Unavailable errors."""
    return render_template(
        "error.html",
        error_code=503,
        error_title=_("Service Unavailable"),
        error_message=_("The service is temporarily unavailable."),
        error_icon="tools",
        error_color="yellow",
        info_color="yellow",
        show_retry=True,
        traceback_info=get_traceback_info(error),
        error=error,
    ), 503


@app.errorhandler(504)
def gateway_timeout(error) -> ...:
    """Handle 504 Gateway Timeout errors."""
    return render_template(
        "error.html",
        error_code=504,
        error_title=_("Gateway Timeout"),
        error_message=_("The server took too long to respond."),
        error_icon="hourglass-split",
        error_color="orange",
        info_color="orange",
    ), 504


# Generic error handler for any unhandled exceptions
@app.errorhandler(Exception)
def handle_exception(error) -> ...:
    """Handle any unhandled exceptions."""
    from werkzeug.exceptions import HTTPException

    # If it's already an HTTP error, let the specific handler deal with it
    if isinstance(error, HTTPException):
        return error

    # For any other exception, treat as 500 error
    app.logger.error(f"Unhandled exception: {error}", exc_info=True)
    return render_template(
        "error.html",
        error_code=500,
        error_title=_("Internal Server Error"),
        error_message=_("An unexpected error occurred."),
        error_icon="gear-wide-connected",
        error_color="red",
        info_color="red",
        show_retry=True,
        traceback_info=get_traceback_info(error),
        error=error,
    ), 500


# Test routes for error handlers (only available in debug mode)
@app.route("/test-error/<int:error_code>")
def test_error(error_code) -> ...:
    """Test route to trigger specific HTTP errors for testing purposes."""
    if app.config.get("DEBUG"):
        abort(error_code)
    else:
        abort(404)  # In production, don't expose this functionality


@app.route("/test-exception")
def test_exception() -> ...:
    """Test route to trigger an unhandled exception."""
    if app.config.get("DEBUG"):
        raise Exception("This is a test exception to verify error handling")
    else:
        abort(404)  # In production, don't expose this functionality
