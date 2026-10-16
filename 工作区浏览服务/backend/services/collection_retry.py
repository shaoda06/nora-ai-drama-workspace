"""Classify collection failures; retry downloads, never generation or local file conflicts."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import errno
import stat

DELAYS = (10, 30, 60)


class EvidenceError(ValueError):
    """A local receipt failure is not a transient remote connection failure."""


def failure(error, client_error, **target):
    issue = {**target, 'error': str(error), 'code': type(error).__name__, 'retryable': False}
    if isinstance(error, client_error):
        issue['code'] = error.code
        issue['retryable'] = error.code in ('transport_error', 'incomplete_download')
        if error.code == 'http_error':
            status = error.details['http_status']
            issue.update(http_status=status, retryable=status in (408, 429, 500, 502, 503, 504),
                         error=f'HTTP {status}：{error}')
            issue.update({key: error.details[key] for key in ('response', 'retry_after') if key in error.details})
            value = error.details.get('retry_after')
            if status == 429 and value is not None:
                try:
                    seconds = (int(value) if value.isascii() and value.isdecimal() else
                               (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                    issue['retry_after_seconds'] = max(0, seconds)
                except (ValueError, TypeError, OverflowError) as invalid:
                    issue.update(retryable=False, error=f'HTTP 429：Retry-After格式无效，需核对远端响应（{invalid}）')
    elif isinstance(error, OSError):
        issue['retryable'] = isinstance(error, (TimeoutError, ConnectionError)) or error.errno in (
            errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED, errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH)
    return issue


def saved_files(receipt, candidate):
    """One metadata observation supplies both the proof and receipt existence."""
    try:
        receipt_stamp = receipt.stat()
    except FileNotFoundError:
        return None, False
    try:
        candidate_stamp = candidate.stat()
    except FileNotFoundError:
        return None, True
    stamps = receipt_stamp, candidate_stamp
    proof = tuple((value.st_size, value.st_mtime_ns) for value in stamps) if all(
        stat.S_ISREG(value.st_mode) for value in stamps) else None
    return proof, True
