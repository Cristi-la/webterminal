class WebSocketManager {
    constructor(url, terminal = null, editor = null) {
        this.websocket = new WebSocket(url)

        if (terminal) {
            this.terminal = terminal
        }

        if (editor) {
            this.editor = editor
        }
    }

    setupTerminalLogic() {
        this.websocket.onerror = (e) => {
            this.terminal.writeMessage('WebSocket connection error\n\r')
        };

        this.websocket.onopen = () => {
            if (this.terminal) {
                this.terminal.setWebSocket(this.websocket);
                this.terminal.performResize()
            }
        };

        this.websocket.onmessage = (e) => {
            let data = JSON.parse(e.data);

            if (data.message) {
                switch (data.message.type) {
                    case 'error':
                        this.terminal.writeMessage(data.message.content + '\n\r')
                        break
                    case 'info':
                        this.terminal.writeMessage(data.message.content);
                        break
                    case 'action':
                        if (data.message.content.type === 'require_reconnect') {
                            createReconnectButton(data.message.content.session_saved, this.terminal)
                        } else if (data.message.content.type === 'reconnect_successful') {
                            removeReconnectButton()
                        } else if (data.message.content.type === 'del_tab') {
                            if (window.parent && typeof window.parent.removeElementsForSession === 'function') {
                                window.parent.removeElementsForSession(data.message.content.session_id)
                            }
                        } else if (data.message.content.type === 'load_content' && this.terminal.termContentLoadedFromDb === false) {
                            this.terminal.writeMessage(data.message.content.data)
                            this.terminal.termContentLoadedFromDb = true
                        }
                }
            }
        };
    }

    setupNoteLogic() {
        this.websocket.onopen = () => {
            if (this.editor) {
                this.editor.setWebSocket(this.websocket);
            }
        };

        this.websocket.onmessage = (e) => {
            let data = JSON.parse(e.data);
            if (data.message) {
                switch (data.message.type) {
                    case 'action':
                        if (data.message.content.type === 'del_tab') {
                            if (window.parent && typeof window.parent.removeElementsForSession === 'function') {
                                window.parent.removeElementsForSession(data.message.content.session_id)
                            }
                        } else if (data.message.content.type === 'insert') {
                            this.editor.insertText(data.message.content.text, data.message.content.index)
                        } else if (data.message.content.type === 'delete') {
                            this.editor.deleteText(data.message.content.length, data.message.content.index)
                        } else if (data.message.content.type === 'format-change') {
                            this.editor.applyFormatChanges(data.message.content.format_type, data.message.content.value,
                                data.message.content.index, data.message.content.length)
                        } else if (data.message.content.type === 'load_content') {
                            this.editor.loadDelta(data.message.content.delta)
                        }
                }
            }
        }

    }
}
