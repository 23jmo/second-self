"use client";

import { useState, useRef, useEffect } from "react";
import { postChat } from "@/lib/api";
import type { ActionTaken } from "@/lib/api";
import MascotFace from "@/components/mascot/MascotFace";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  actions?: ActionTaken[];
}

interface ChatScreenProps {
  sessionId: string;
  name: string;
}

export default function ChatScreen({ sessionId, name }: ChatScreenProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", text }]);
    setLoading(true);

    try {
      const resp = await postChat(text, sessionId);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: resp.response, actions: resp.actions_taken },
      ]);
    } catch (err) {
      console.error("Chat failed:", err);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "Something went wrong. Please try again." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex flex-col items-center w-full max-w-[680px] px-4 h-[80vh]">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <MascotFace className="w-12 h-12" />
        <div>
          <p className="text-lg font-semibold text-black">{name}&apos;s second self</p>
          <p className="text-sm text-black/50">ask me anything</p>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 w-full overflow-y-auto flex flex-col gap-4 pb-4"
      >
        {messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-black/30 text-center text-lg">
              try &quot;what&apos;s on my calendar this week?&quot;
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-primary text-white"
                  : "bg-gray-100 text-black"
              }`}
            >
              <p className="text-sm sm:text-base whitespace-pre-wrap">{msg.text}</p>
              {msg.actions && msg.actions.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {msg.actions.map((action, j) => (
                    <span
                      key={j}
                      className="text-xs bg-black/10 rounded-full px-3 py-1"
                    >
                      {action.tool}: {action.summary}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl px-4 py-3">
              <p className="text-sm text-black/50 animate-pulse">thinking...</p>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="w-full flex gap-3 pt-4 border-t border-black/10">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="ask your second self..."
          className="flex-1 bg-gray-100 rounded-full px-5 py-3 text-sm sm:text-base outline-none focus:ring-2 focus:ring-primary/30"
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={!input.trim() || loading}
          className="bg-primary text-white rounded-full px-6 py-3 text-sm sm:text-base font-medium disabled:opacity-40 transition-opacity"
        >
          send
        </button>
      </div>
    </div>
  );
}
