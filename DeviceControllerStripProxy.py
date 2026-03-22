"""
DeviceControllerStripProxy.py — Thread-safe proxy for DeviceControllerStrip.

The device parameter sliders run on Ableton's main thread, but the stepless
fader animation needs to keep running smoothly between parameter updates.
This proxy solves the threading problem by running the actual
:class:`~DeviceControllerStripServer.DeviceControllerStripServer` on a
dedicated background thread and forwarding all method calls through a pair
of thread-safe queues.

Architecture
------------
::

    Main thread                     Background thread
    ───────────────────────         ─────────────────────────────────
    DeviceControllerStripProxy  ──→  DeviceControllerStripServer.run()
        _request_queue (put)     ←──  _request_queue (get)
        _response_queue (get)    ──→  _response_queue (put)

Method dispatch
~~~~~~~~~~~~~~~
Methods listed in ``non_returns`` fire-and-forget: the proxy sends the call
and immediately returns ``None``.

Methods listed in ``returning`` block until the server processes the call and
puts a response on ``_response_queue``.

All other method names default to fire-and-forget to keep the main thread
responsive.

Constants
---------
non_returns (list[str]): Method names that do not need a return value.
returning  (list[str]): Method names whose return value must be collected.
"""

import traceback
import time
from threading import Thread
from functools import partial

try:
    import Queue as queue
except ModuleNotFoundError:
    import queue

from .DeviceControllerStripServer import DeviceControllerStripServer
from .Log import log

# Methods that do not require a return value (fire-and-forget)
non_returns = [
    "set_precision_mode", "set_stepless_mode", "shutdown",
    "update", "reset_if_no_parameter", "_button_value", "connect_to",
    "release_parameter", "set_parent",
]

# Methods that block until the server responds with a value
returning = ["set_enabled", "param_name", "param_value", "__ne__"]


class DeviceControllerStripProxy():
    """
    Transparent proxy that forwards calls to a background DeviceControllerStripServer.

    Instantiated once per slider column (0–7) by
    :class:`~DeviceControllerComponent.DeviceControllerComponent`.

    Attributes:
        _request_queue (queue.Queue): Main-thread → server call queue.
        _response_queue (queue.Queue): Server → main-thread response queue.
        failed (bool): Set to ``True`` if the background server raises an
            unhandled exception or a response times out; subsequent calls
            become no-ops.
        column (int): Zero-based column index (0–7) for debugging.
        request_id (int): Auto-incrementing token used to match responses to
            their originating requests.
        server (DeviceControllerStripServer): The actual worker object running
            on the background thread.
        _server_process (Thread): The background thread running the server loop.
    """

    def __init__(self, buttons, control_surface, column, parent=None):
        """
        Create the proxy, start the background server thread.

        Args:
            buttons (tuple): Physical button elements for this slider column.
            control_surface: The owning Launchpad control surface.
            column (int): Column index (0–7).
            parent: The owning :class:`~DeviceControllerComponent.DeviceControllerComponent`.
        """
        self._request_queue = queue.Queue()
        self._response_queue = queue.Queue()
        self.failed = False
        self.column = column
        self.request_id = 0
        self.server = DeviceControllerStripServer(
            buttons, control_surface, column,
            request_queue=self._request_queue,
            response_queue=self._response_queue,
            parent=parent)
        self._server_process = Thread(target=self.server.run)
        self._server_process.start()

    def __getattr__(self, item):
        """
        Intercept attribute access and return the appropriate call handler.

        If the proxy has failed, all attribute accesses return ``None`` to
        avoid cascading errors.

        Args:
            item (str): Attribute name being accessed.

        Returns:
            callable: A partial that routes the call through the queue system.
        """
        if self.failed:
            return
        if item in non_returns:
            return partial(self._call_non_return_handler, item)
        elif item in returning:
            return partial(self._call_return_handler, item)
        else:
            # Unknown methods default to fire-and-forget
            return partial(self._call_non_return_handler, item)

    def _call_non_return_handler(self, name, *args, **kwargs):
        """
        Enqueue a fire-and-forget method call.

        Args:
            name (str): Name of the method to call on the server.
            *args: Positional arguments forwarded to the method.
            **kwargs: Keyword arguments forwarded to the method.
        """
        self.request_id += 1
        self._request_queue.put((name, self.request_id, args, kwargs))

    def _call_return_handler(self, name, *args, **kwargs):
        """
        Enqueue a method call and block until the server responds.

        Waits up to 10 seconds for the matching response token before giving
        up and marking the proxy as failed.

        Args:
            name (str): Name of the method to call on the server.
            *args: Positional arguments forwarded to the method.
            **kwargs: Keyword arguments forwarded to the method.

        Returns:
            The return value from the server method, or ``None`` on failure.
        """
        self.request_id += 1
        current_id = self.request_id
        self._request_queue.put((name, current_id, args, kwargs))
        try:
            while True:
                token, response = self._response_queue.get(timeout=10)
                if token == current_id:
                    break
                # Discard stale responses from earlier requests
                if response == "ERROR":
                    self.failed = True
                time.sleep(0.01)
            if response == 'None' and False:
                return None
            return response
        except queue.Empty:
            # Timeout waiting for the server — mark proxy as failed
            self.failed = True
            log(traceback.format_stack())
            return
