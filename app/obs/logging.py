import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logging():
    log_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s %(request_id)s %(tenant_key)s',
        timestamp=True
    )
    log_handler.setFormatter(formatter)
    
    # Custom filter to inject request context
    class ContextFilter(logging.Filter):
        def filter(self, record):
            try:
                from ..core.context import request_context_var
                ctx = request_context_var.get()
                record.request_id = ctx.request_id
                record.tenant_key = ctx.tenant_key
            except Exception:
                record.request_id = 'N/A'
                record.tenant_key = 'N/A'
            return True
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.INFO)
    root_logger.addFilter(ContextFilter())
