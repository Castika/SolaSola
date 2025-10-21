import json
import queue
import logging

# Use the standard logging module, which is thread-safe and can be used
# outside of Flask's application context.
logger = logging.getLogger(__name__)


class SSEManager:
    """
    Manages Server-Sent Events (SSE) connections and message broadcasting.
    This class is thread-safe.
    """
    def __init__(self):
        self.clients = []

    def subscribe(self):
        """
        Subscribes a new client to the event stream.
        Returns a dedicated queue for the client to receive messages.
        """
        client_queue = queue.Queue()
        self.clients.append(client_queue)
        return client_queue

    def unsubscribe(self, client_queue):
        """Removes a client's queue from the list of subscribers."""
        try:
            self.clients.remove(client_queue)
        except ValueError:
            # This can happen if a client disconnects and the generator tries
            # to
            # unsubscribe multiple times. It's safe to ignore.
            pass

    def _format_sse(self, data: str, event: str = None) -> str:
        """Formats data as a Server-Sent Event string."""
        message = f"data: {data}\n\n"
        if event:
            message = f"event: {event}\n{message}"
        return message

    def broadcast(self, message: dict):
        """
        Broadcasts a message to all subscribed clients.
        The message must be a JSON-serializable dictionary.
        """

        logger.info(f"SSE BROADCAST: {message}")
        json_message = json.dumps(message)
        # We iterate over a copy of the list (`list(self.clients)`) to prevent
        # race conditions if another thread modifies the list during iteration.
        for client_queue in list(self.clients):
            try: # noqa
                client_queue.put(json_message)
            except Exception as e:
                # If putting a message into a queue fails, it might mean the
                # client is gone. It's safer to let the `stream` generator
                # handle the
                # stream generator handle the cleanup on disconnect.
                logger.warning(f"Could not put message in client queue: {e}")

    def stream(self):
        """
        A generator function that yields events for a single client connection.
        This is intended to be used within a Flask route.
        """
        client_queue = self.subscribe()
        logger.info(f"SSE client connected. Total clients: {len(self.clients)}")
        try: # noqa
            # Send an initial connection confirmation event. This immediately
            # triggers the 'onopen' event on the client and prevents an initial
            # delay while the queue waits for its first message.
            yield ":connected\n\n"
            while True:
                try:
                    # Block for up to 15 seconds waiting for a message.
                    message = client_queue.get(timeout=15)
                    yield self._format_sse(data=message)
                except queue.Empty:
                    # If no message is received, send a comment as a heartbeat
                    # to prevent the connection from timing out.
                    yield ":heartbeat\n\n"
        except GeneratorExit:
            # This is raised when the client disconnects.
            # It's the natural and expected way to clean up.
            pass
        finally:
            self.unsubscribe(client_queue)
            logger.info(f"SSE client disconnected. Total clients: "
                        f"{len(self.clients)}")
