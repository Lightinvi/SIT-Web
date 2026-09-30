"""Structured request logs with byte-bounded, cross-process rotation on Linux/WSL."""
from datetime import datetime, timezone
import fcntl
import json
import logging
from pathlib import Path
import time
import traceback
from uuid import uuid4

from flask import g, has_request_context, request

MAX_LOG_BYTES = 10 * 1024 * 1024


class JsonFormatter(logging.Formatter):
    """Serialize one event without request bodies, headers, query strings, or tokens."""

    def format(self, record):
        """Include UTC time, severity, worker PID, and the request correlation ID."""
        data = {'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                'level': record.levelname, 'pid': record.process,
                'requestId': getattr(g, 'request_id', None) if has_request_context() else None,
                'message': record.getMessage()}
        if hasattr(record, 'request_summary'):
            data.update(record.request_summary)
        if record.exc_info:
            # Retain diagnostic frames, not exception values that may contain credentials.
            data['exceptionType'] = record.exc_info[0].__name__
            data['traceback'] = [f'{frame.filename}:{frame.lineno} in {frame.name}'
                                 for frame in traceback.extract_tb(record.exc_info[2])]
        return json.dumps(data, ensure_ascii=False)


class BoundedFileHandler(logging.Handler):
    """Keep exactly one active log and at most one backup under a shared file lock.

    Reopen the active path per emission so Gunicorn workers never keep writing to
    renamed files. The separate lock inode remains stable during rotation.
    """

    def __init__(self, directory, max_bytes=MAX_LOG_BYTES):
        """Configure a bounded JSON-lines sink and create its mounted directory."""
        super().__init__(logging.INFO)
        if max_bytes < 256:
            raise ValueError('Log size limit must be at least 256 bytes')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'app.log'
        self.backup = self.directory / 'app.log.1'
        self.lock_path = self.directory / '.app.lock'
        self.max_bytes = max_bytes

    def emit(self, record):
        """Measure encoded bytes, truncate oversized events, then rotate before writing."""
        try:
            message = self.format(record)
            limit = min(self.max_bytes, 64 * 1024)
            payload = (message + '\n').encode('utf-8')
            if len(payload) > limit:
                data = json.loads(message)
                data.pop('traceback', None)
                data['truncated'] = True
                data['message'] = data.get('message', '')[:limit // 8]
                payload = (json.dumps(data, ensure_ascii=False) + '\n').encode('utf-8')
                if len(payload) > limit:
                    payload = (json.dumps({'level': record.levelname, 'truncated': True,
                                           'message': 'Oversized log event omitted'}) + '\n').encode()
            with self.lock_path.open('a+b') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                if self.path.exists() and self.path.stat().st_size + len(payload) > self.max_bytes:
                    self.path.replace(self.backup)
                with self.path.open('ab') as output:
                    output.write(payload)
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception:
            self.handleError(record)


def init_logging(app):
    """Install an app-scoped INFO logger and request completion tracing."""
    logger = logging.Logger('sit-web', level=logging.INFO)
    logger.propagate = False
    if app.config.get('LOG_ENABLED', not app.testing):
        handler = BoundedFileHandler(app.config['LOG_DIRECTORY'])
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    else:
        logger.addHandler(logging.NullHandler())
    app.__dict__['logger'] = logger

    @app.before_request
    def begin_request():
        """Generate a trusted correlation ID and monotonic request start time."""
        g.request_id = str(uuid4())
        g.request_started = time.perf_counter()

    @app.after_request
    def end_request(response):
        """Log a route template and status, and expose the correlation ID to clients."""
        response.headers['X-Request-ID'] = g.request_id
        if request.endpoint == 'health' and 200 <= response.status_code < 300:
            return response
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(level, 'HTTP request completed', extra={'request_summary': {
            'method': request.method, 'route': request.url_rule.rule if request.url_rule else '[unmatched]',
            'status': response.status_code,
            'durationMs': round((time.perf_counter() - g.request_started) * 1000, 2),
        }})
        return response
