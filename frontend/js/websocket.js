/* ============================================================
   websocket.js — WebSocket connection manager with auto-reconnect
   ============================================================ */

class WSManager {
    constructor() {
        this.ws = null;
        this.runId = null;
        this.handlers = {};
        this.reconnectAttempts = 0;
        this.maxReconnect = 5;
        this.connected = false;
    }

    /**
     * Open a WebSocket connection for the given run ID.
     * Resets the reconnect counter before connecting.
     * @param {string} runId
     */
    connect(runId) {
        this.runId = runId;
        this.reconnectAttempts = 0;
        this.maxReconnect = 5;  // Reset on new connection
        this._connect();
    }

    /** @private */
    _connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws/runs/${this.runId}`;

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this.connected = true;
            this.reconnectAttempts = 0;
            this._emit('connected');
        };

        this.ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                this._emit(msg.type, msg.data);
            } catch (err) {
                console.error('WS parse error:', err);
            }
        };

        this.ws.onclose = () => {
            this.connected = false;
            this._emit('disconnected');
            this._tryReconnect();
        };

        this.ws.onerror = (err) => {
            console.error('WS error:', err);
        };
    }

    /**
     * Attempt to reconnect with exponential back-off.
     * @private
     */
    _tryReconnect() {
        if (this.reconnectAttempts >= this.maxReconnect) {
            this._emit('reconnect_failed');
            return;
        }
        this.reconnectAttempts++;
        const delay = Math.pow(2, this.reconnectAttempts) * 1000;
        setTimeout(() => this._connect(), delay);
    }

    /**
     * Send a typed message over the WebSocket.
     * Silently no-ops if the socket is not open.
     * @param {string} type
     * @param {object} data
     */
    send(type, data = {}) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, data }));
        }
    }

    /**
     * Register an event handler.
     * @param {string}   event
     * @param {Function} handler
     */
    on(event, handler) {
        if (!this.handlers[event]) this.handlers[event] = [];
        this.handlers[event].push(handler);
    }

    /**
     * Remove a previously registered event handler.
     * @param {string}   event
     * @param {Function} handler
     */
    off(event, handler) {
        if (this.handlers[event]) {
            this.handlers[event] = this.handlers[event].filter(h => h !== handler);
        }
    }

    /** @private */
    _emit(event, data) {
        (this.handlers[event] || []).forEach(h => h(data));
    }

    /**
     * Cleanly close the connection and prevent any further reconnect attempts.
     */
    disconnect() {
        this.maxReconnect = 0; // Prevent reconnect
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }
}
