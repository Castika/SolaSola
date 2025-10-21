/**
 * sse_client.js
 * 
 * Manages the Server-Sent Events (SSE) connection for the entire application.
 * It provides a singleton object to connect, disconnect, and subscribe to server events.
 */

const sseClient = (() => {
    let eventSource = null;
    const subscribers = {};
    let clientId = null;

    function getClientId() {
        if (!clientId) {
            // Try to get it from session storage to persist across reloads
            clientId = sessionStorage.getItem('sola-sse-clientId');
            if (!clientId) {
                clientId = `client-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                sessionStorage.setItem('sola-sse-clientId', clientId);
            }
        }
        return clientId;
    }

    function connect() {
        if (eventSource) {
            return; // Already connected
        }

        eventSource = new EventSource('/api/model-status-stream');

        eventSource.onmessage = (event) => {
            try {
                // All messages are expected to be in the format { action: "...", payload: { ... } }
                const message = JSON.parse(event.data);
                // Dispatch to a generic 'message' subscriber. The subscriber is responsible for routing.
                if (subscribers['message']) {
                    subscribers['message'].forEach(callback => {
                        try {
                            callback(message);
                        } catch (e) {
                            console.error(`[${new Date().toISOString()}] SSE Client: Error in 'message' subscriber:`, e);
                        }
                    });
                }
            } catch (e) {
                console.error(`[${new Date().toISOString()}] SSE Client: Error parsing message data.`, e);
            }
        };

        eventSource.onerror = (err) => {
            console.error(`[${new Date().toISOString()}] SSE Client: EventSource failed:`, err);
            eventSource.close();
            eventSource = null;
            // Redirect to the offline page, which will handle polling for reconnection.
            window.location.href = '/offline';
        };
    }

    function subscribe(eventName, callback) {
        if (!subscribers[eventName]) {
            subscribers[eventName] = [];
        }
        subscribers[eventName].push(callback);
    }

    return {
        connect,
        subscribe,
        getClientId
    };
})();

export default sseClient;
