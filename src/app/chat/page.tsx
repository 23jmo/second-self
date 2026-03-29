"use client";

import ChatView from "@/components/chat/ChatView";

export default function ChatPage() {
  return (
    <ChatView
      userName="Johnathan"
      vncStreamUrl="http://localhost:8421/stream"
      onSendMessage={(msg) => {
        console.log("Send:", msg);
        // TODO: POST to orchestrator at localhost:8420/command
      }}
    />
  );
}
