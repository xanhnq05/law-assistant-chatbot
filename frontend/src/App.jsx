import { useState, useRef, useEffect } from 'react'
import './App.css'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function sendMessage() {
    const text = input.trim()
    if (!text || loading) return

    // Thêm tin nhắn user + ô loading cho bot
    const userMsg = { role: 'user', text }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, top_k: 5 }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      const botMsg = {
        role: 'bot',
        text: data.answer,
        sources: data.sources || [],
      }
      setMessages(prev => [...prev, botMsg])
    } catch (e) {
      const errMsg = { role: 'error', text: `Lỗi: ${e.message}` }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setLoading(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="app">
      <div className="header">
        <h1>Trợ lý Luật Giao thông</h1>
        <p>Luật Trật tự, An toàn Giao thông Đường bộ 36/2024/QH15</p>
      </div>

      <div className="messages">
        {messages.length === 0 && !loading && (
          <div className="empty">
            <p>Hỏi tôi bất cứ điều gì về luật giao thông đường bộ.</p>
            <p style={{ marginTop: 8, fontSize: 12 }}>
              Ví dụ: "Người đi bộ qua đường phải tuân theo quy tắc gì?"
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div>{m.text}</div>
            {m.sources && m.sources.length > 0 && (
              <div className="sources">
                <strong>Nguồn tham khảo:</strong>
                {m.sources.map((s, j) => (
                  <div key={j}>
                    • {s.citation} (score: {s.score.toFixed(2)})
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {loading && <div className="typing">Đang trả lời...</div>}
        <div ref={messagesEndRef} />
      </div>

      <div className="input-area">
        <input
          type="text"
          placeholder="Nhập câu hỏi..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
        />
        <button onClick={sendMessage} disabled={loading || !input.trim()}>
          Gửi
        </button>
      </div>
    </div>
  )
}

export default App
