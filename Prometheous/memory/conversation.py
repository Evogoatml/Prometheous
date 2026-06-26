import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

@dataclass
class ConversationEntry:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

class ConversationMemory:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.history: List[ConversationEntry] = []
        self.last_target: Optional[str] = None
        self.last_plan: Optional[Dict[str, Any]] = None
        self.tool_results: List[str] = []

    def add(self, role: str, content: str, metadata: Dict[str, Any] = None):
        self.history.append(ConversationEntry(role=role, content=content, metadata=metadata or {}))

    def get_history(self, limit: int = 20) -> List[Dict[str, str]]:
        return [{"role": e.role, "content": e.content} for e in self.history[-limit:]]

    def add_tool_result(self, tool: str, result: str):
        self.tool_results.append(f"[{tool}]\n{result}")

    def clear(self):
        self.history.clear()
        self.tool_results.clear()
        self.last_target = None
        self.last_plan = None

class ConversationStore:
    def __init__(self):
        self.conversations: Dict[int, ConversationMemory] = {}

    def get(self, chat_id: int) -> ConversationMemory:
        if chat_id not in self.conversations:
            self.conversations[chat_id] = ConversationMemory(chat_id)
        return self.conversations[chat_id]

    def clear(self, chat_id: int):
        if chat_id in self.conversations:
            self.conversations[chat_id].clear()
