"""
Log.py — Optional file-based logging utility for Launchpad95.

When ``Settings.LOGGING`` is ``True`` this module:
  1. Ensures the log directory exists at
     ``~/Documents/Ableton/User Library/Remote Scripts/``
  2. Appends a separator line (``====================``) to ``log.txt`` on
     import so that each Ableton session is clearly delimited.
  3. Exposes a ``log(message)`` function that appends numbered lines to
     ``log.txt``.

When ``Settings.LOGGING`` is ``False`` the ``log()`` function is a no-op and
no files are created or written.

Usage::

    from .Log import log
    log("Something happened")
    log(["line one", "line two"])   # lists are joined with newlines
"""

import os
from .Settings import Settings

# Derive the log file path from the current user's home directory so the script
# works on any machine without hard-coded paths.
USER_HOME = os.path.expanduser('~')
LOG_DIRECTORY = USER_HOME + "/Documents/Ableton/User Library/Remote Scripts"
LOG_FILE = LOG_DIRECTORY + "/log.txt"

if Settings.LOGGING:
    # Create the log directory if it does not already exist.
    # Python 2 compatibility: exist_ok was added in Python 3.2, so we catch
    # TypeError and fall back to the two-step create-and-ignore pattern.
    try:
        os.makedirs(LOG_DIRECTORY, exist_ok=True)
    except TypeError:
        try:
            os.makedirs(LOG_DIRECTORY)
        except OSError:
            pass  # Directory already exists

    # Write a session separator so multiple runs are easy to distinguish.
    with open(LOG_FILE, 'a') as f:
        f.write('====================\n')

# Global counter that prefixes every log line with a unique sequential number,
# making it easy to correlate log entries with code flow.
log_num = 0


def log(message):
    """
    Append a numbered message to the Launchpad95 log file.

    Does nothing when ``Settings.LOGGING`` is ``False``.

    Args:
        message (str | list[str]): The text to log.  If a list is provided its
            elements are joined with newline characters before writing.
    """
    global log_num
    if Settings.LOGGING:
        with open(LOG_FILE, 'a') as f:
            if type(message) == list:
                message = '\n'.join(message)
            f.write(str(log_num) + ' ' + str(message) + '\n')
        log_num += 1
