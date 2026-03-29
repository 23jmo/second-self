"use client";

import { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "motion/react";

// ─── Types ──────────────────────────────────────

type MessageRole = "twin" | "user";

interface ToolCall {
  name: string;
  args: string;
}

interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  toolCall?: ToolCall;
}

interface ChatViewProps {
  userName: string;
  onSendMessage?: (message: string) => void;
  messages?: ChatMessage[];
  isThinking?: boolean;
  vncStreamUrl?: string;
}

// ─── Sub-components ─────────────────────────────

function Notch() {
  return (
    <div className="flex justify-center pt-0 pb-1">
      <div className="relative">
        <div className="w-[200px] h-[28px] bg-black rounded-b-[14px]" />
        <div className="absolute -left-2 -right-2 top-0 h-[20px] bg-black" />
      </div>
    </div>
  );
}

function TwinMessage({ content, timestamp }: { content: string; timestamp: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="flex flex-col gap-1 max-w-[85%]"
    >
      <div className="bg-[#141417] border border-[#333] rounded-[12px] px-3 py-2.5">
        <p className="text-[13px] text-[#f5f5f7] italic leading-relaxed">{content}</p>
      </div>
      <span className="text-[10px] text-[#8e8e93] pl-1">{timestamp}</span>
    </motion.div>
  );
}

function UserMessage({ content, timestamp }: { content: string; timestamp: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="flex flex-col gap-1 items-end self-end max-w-[85%]"
    >
      <div className="bg-[#2c2c2e] rounded-[12px] px-3 py-2.5">
        <p className="text-[13px] text-[#f5f5f7] leading-relaxed">{content}</p>
      </div>
      <span className="text-[10px] text-[#8e8e93] pr-1">{timestamp}</span>
    </motion.div>
  );
}

function ToolCallPill({ name, args }: ToolCall) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="bg-primary/10 border border-primary/40 rounded-[8px] px-2.5 py-1 inline-flex items-center gap-1.5 self-start"
    >
      <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
      <span className="text-[11px] font-medium text-primary">
        {name} {args}
      </span>
    </motion.div>
  );
}

function ThinkingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex gap-1 px-3 py-2"
    >
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-primary/60"
          animate={{ y: [0, -4, 0] }}
          transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </motion.div>
  );
}

function VncPip({ streamUrl }: { streamUrl?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.3 }}
      className="bg-[#262629] border-2 border-primary rounded-[10px] overflow-hidden shadow-[0_0_12px_rgba(156,161,97,0.25)] cursor-pointer self-end"
      style={{ width: 160, height: 100 }}
    >
      <div className="flex items-center gap-1 px-2 py-1">
        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
        <span className="text-[8px] font-medium text-primary uppercase tracking-wider">Live</span>
      </div>
      {streamUrl ? (
        <img
          src={streamUrl}
          alt="Twin's Desktop"
          className="w-full h-[72px] object-cover"
        />
      ) : (
        <div className="flex items-center justify-center h-[72px]">
          <span className="text-[9px] text-[#8e8e93]">Twin&apos;s Desktop</span>
        </div>
      )}
    </motion.div>
  );
}

function MessageInput({
  onSend,
  disabled,
}: {
  onSend: (msg: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  };

  return (
    <div className="bg-[#2c2c2e] rounded-[20px] flex items-center px-4 py-2 gap-2">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSend()}
        placeholder="Message your Twin..."
        disabled={disabled}
        className="flex-1 bg-transparent text-[13px] text-[#f5f5f7] placeholder:text-[#8e8e93] outline-none disabled:opacity-50"
      />
      <button
        onClick={handleSend}
        disabled={!value.trim() || disabled}
        className="w-7 h-7 rounded-full bg-primary flex items-center justify-center transition-opacity hover:opacity-80 disabled:opacity-30"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
          <path d="M7 11L12 6L17 11M12 6V18" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}

// ─── Main Component ─────────────────────────────

export default function ChatView({
  userName,
  onSendMessage,
  messages: externalMessages,
  isThinking = false,
  vncStreamUrl,
}: ChatViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const [internalMessages] = useState<ChatMessage[]>([
    {
      id: "1",
      role: "twin",
      content: `Hey ${userName}, I've been looking into some recent AI research. What should we work on?`,
      timestamp: "2:14 PM",
    },
    {
      id: "2",
      role: "user",
      content: "Search for quantum computing papers",
      timestamp: "2:14 PM",
    },
    {
      id: "3",
      role: "twin",
      content: "On it. Opening Google Scholar now...",
      timestamp: "2:15 PM",
      toolCall: { name: "browser_goto", args: "scholar.google.com" },
    },
    {
      id: "4",
      role: "twin",
      content: "Found 3 papers on quantum error correction. I've got them open in tabs. The most cited one is from MIT, published last month.",
      timestamp: "2:15 PM",
    },
  ]);

  const messages = externalMessages || internalMessages;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = (msg: string) => {
    onSendMessage?.(msg);
  };

  return (
    <div className="bg-[#212124] w-full min-h-dvh flex flex-col items-center">
      <Notch />

      {/* Chat Panel */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="w-full max-w-[440px] mx-auto bg-[#1c1c1e] border border-[#333] rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.5)] flex flex-col overflow-hidden"
        style={{ height: "calc(100dvh - 60px)", maxHeight: 600 }}
      >
        {/* Messages area */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-3 py-4 flex flex-col gap-3 scrollbar-thin scrollbar-thumb-[#333] scrollbar-track-transparent"
        >
          <AnimatePresence>
            {messages.map((msg) => (
              <div key={msg.id} className="flex flex-col gap-1.5">
                {msg.role === "twin" ? (
                  <TwinMessage content={msg.content} timestamp={msg.timestamp} />
                ) : (
                  <UserMessage content={msg.content} timestamp={msg.timestamp} />
                )}
                {msg.toolCall && (
                  <ToolCallPill name={msg.toolCall.name} args={msg.toolCall.args} />
                )}
              </div>
            ))}
          </AnimatePresence>

          <AnimatePresence>
            {isThinking && <ThinkingIndicator />}
          </AnimatePresence>

          {/* VNC PiP */}
          <VncPip streamUrl={vncStreamUrl} />
        </div>

        {/* Mascot + Input */}
        <div className="px-3 pb-3 pt-1">
          <div className="flex justify-center -mb-1">
            <img
              src="/mascot.gif"
              alt="Second Self mascot"
              className="w-10 h-auto opacity-70"
            />
          </div>
          <MessageInput onSend={handleSend} disabled={isThinking} />
        </div>
      </motion.div>
    </div>
  );
}
