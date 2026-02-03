let ws = null;
let chatId = null;

const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const statusEl = document.getElementById('status');

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        statusEl.textContent = 'Connected';
        statusEl.style.color = '#4a9eff';
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'system' && data.chat_id) {
            chatId = data.chat_id;
        }
        
        addMessage(data);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        statusEl.textContent = 'Connection error';
        statusEl.style.color = '#ff4a4a';
    };
    
    ws.onclose = () => {
        statusEl.textContent = 'Disconnected. Reconnecting...';
        statusEl.style.color = '#888';
        setTimeout(connect, 3000);
    };
}

function addMessage(data) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${data.type || 'user'}`;
    
    const metaDiv = document.createElement('div');
    metaDiv.className = 'message-meta';
    metaDiv.textContent = new Date().toLocaleTimeString();
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = data.content;
    
    msgDiv.appendChild(metaDiv);
    msgDiv.appendChild(contentDiv);
    messagesEl.appendChild(msgDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function sendMessage() {
    const content = inputEl.value.trim();
    if (!content || !ws || ws.readyState !== WebSocket.OPEN) return;
    
    ws.send(JSON.stringify({
        content: content,
        sender_id: chatId
    }));
    
    addMessage({
        type: 'user',
        content: content
    });
    
    inputEl.value = '';
}

inputEl.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

// Connect on load
connect();
