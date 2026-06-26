#!/usr/bin/env python3
"""
CRDT-based Knowledge Base for Distributed Pentesting Learning
Allows peer-to-peer knowledge sharing with eventual consistency
"""

import json
import hashlib
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict
import threading

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class VectorClock:
    """Vector clock for ordering events"""
    clocks: Dict[str, int] = field(default_factory=dict)
    
    def increment(self, node_id: str):
        self.clocks[node_id] = self.clocks.get(node_id, 0) + 1
        return self.clocks[node_id]
    
    def merge(self, other: 'VectorClock'):
        for node, time in other.clocks.items():
            self.clocks[node] = max(self.clocks.get(node, 0), time)
    
    def happened_before(self, other: 'VectorClock') -> bool:
        for node, time in other.clocks.items():
            if self.clocks.get(node, 0) > time:
                return False
        return self.clocks != other.clocks
    
    def to_dict(self) -> Dict[str, int]:
        return dict(self.clocks)

@dataclass  
class GSetElement:
    """Element in a Grow-only Set CRDT"""
    element_id: str
    content: str
    added_by: str
    timestamp: float
    vector_clock: Dict[str, int]
    tags: List[str] = field(default_factory=list)

class GSetCRDT:
    """Grow-only Set CRDT - append only, no deletions"""
    
    def __init__(self, node_id: str = "local"):
        self.node_id = node_id
        self.elements: Dict[str, GSetElement] = {}
        self.vector_clock = VectorClock()
        self._lock = threading.Lock()
        
    def add(self, content: str, tags: List[str] = None) -> str:
        with self._lock:
            element_id = hashlib.sha256(
                f"{content}{time.time()}{self.node_id}".encode()
            ).hexdigest()[:16]
            
            if element_id in self.elements:
                return element_id
                
            self.vector_clock.increment(self.node_id)
            
            element = GSetElement(
                element_id=element_id,
                content=content,
                added_by=self.node_id,
                timestamp=time.time(),
                vector_clock=self.vector_clock.to_dict(),
                tags=tags or []
            )
            self.elements[element_id] = element
            logger.info(f"Added element: {element_id[:8]}...")
            
            return element_id
    
    def merge(self, other: 'GSetCRDT'):
        """Merge another GSet into this one"""
        with self._lock:
            for elem_id, element in other.elements.items():
                if elem_id not in self.elements:
                    self.elements[elem_id] = element
                elif element.timestamp < self.elements[elem_id].timestamp:
                    self.elements[elem_id] = element
            
            self.vector_clock.merge(other.vector_clock)
            
    def query(self, tag: str = None) -> List[GSetElement]:
        """Query elements by tag"""
        results = []
        for element in self.elements.values():
            if tag is None or tag in element.tags:
                results.append(element)
        return sorted(results, key=lambda x: x.timestamp, reverse=True)
    
    def search(self, query: str) -> List[GSetElement]:
        """Full-text search"""
        query_lower = query.lower()
        results = []
        for element in self.elements.values():
            if query_lower in element.content.lower():
                results.append(element)
        return results
    
    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "elements": [
                {
                    "id": e.element_id,
                    "content": e.content,
                    "added_by": e.added_by,
                    "timestamp": e.timestamp,
                    "tags": e.tags
                }
                for e in self.elements.values()
            ]
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'GSetCRDT':
        crdt = cls(data.get("node_id", "unknown"))
        for elem in data.get("elements", []):
            element = GSetElement(
                element_id=elem["id"],
                content=elem["content"],
                added_by=elem["added_by"],
                timestamp=elem["timestamp"],
                vector_clock={},
                tags=elem.get("tags", [])
            )
            crdt.elements[elem["id"]] = element
        return crdt

@dataclass
class LWWElement:
    """Last-Writer-Wins Register - for updates"""
    value: str
    node_id: str
    timestamp: float
    vector_clock: Dict[str, int]

class LWWRegister:
    """Last-Writer-Wins Register CRDT"""
    
    def __init__(self, key: str):
        self.key = key
        self.value: Optional[LWWElement] = None
        self._lock = threading.Lock()
        
    def set(self, value: str, node_id: str) -> None:
        with self._lock:
            self.value = LWWElement(
                value=value,
                node_id=node_id,
                timestamp=time.time(),
                vector_clock={}
            )
    
    def get(self) -> Optional[str]:
        return self.value.value if self.value else None
    
    def merge(self, other: 'LWWRegister') -> bool:
        """Merge returns True if changed"""
        with self._lock:
            if other.value is None:
                return False
            if self.value is None:
                self.value = other.value
                return True
            if other.value.timestamp > self.value.timestamp:
                self.value = other.value
                return True
            return False

class AWORSet:
    """Add-Wins-Order Replicated Set (more advanced)"""
    
    def __init__(self, node_id: str = "local"):
        self.node_id = node_id
        self.tombstones: Set[str] = set()
        self.elements: Dict[str, GSetElement] = {}
        self._lock = threading.Lock()
        
    def add(self, content: str, tags: List[str] = None) -> str:
        with self._lock:
            element_id = hashlib.sha256(
                f"{content}{time.time()}{self.node_id}".encode()
            ).hexdigest()[:16]
            
            if element_id in self.tombstones:
                self.tombstones.discard(element_id)
                
            element = GSetElement(
                element_id=element_id,
                content=content,
                added_by=self.node_id,
                timestamp=time.time(),
                vector_clock={},
                tags=tags or []
            )
            self.elements[element_id] = element
            return element_id
    
    def remove(self, element_id: str):
        with self._lock:
            self.tombstones.add(element_id)
    
    def merge(self, other: 'AWORSet'):
        with self._lock:
            for elem_id, element in other.elements.items():
                if elem_id not in other.tombstones:
                    if elem_id not in self.tombstones:
                        if elem_id not in self.elements or \
                           element.timestamp > self.elements[elem_id].timestamp:
                            self.elements[elem_id] = element
        
            self.tombstones.update(other.tombstones)
    
    def query(self) -> List[GSetElement]:
        return [
            e for e in self.elements.values()
            if e.element_id not in self.tombstones
        ]

class CRDTKnowledgeBase:
    """Complete CRDT knowledge base with multiple data types"""
    
    def __init__(self, node_id: str = "pentest-bot"):
        self.node_id = node_id
        self.gset = GSetCRDT(node_id)
        self.registers: Dict[str, LWWRegister] = {}
        self.aworset = AWORSet(node_id)
        self._lock = threading.Lock()
        
    def add_vulnerability(self, name: str, description: str, tags: List[str]):
        """Add vulnerability knowledge"""
        content = f"{name}: {description}"
        self.gset.add(content, tags + ["vulnerability"])
        self.aworset.add(content, tags + ["vulnerability"])
        
    def add_payload(self, name: str, payload: str, vuln_type: str):
        """Add exploit payload"""
        content = f"Payload for {name}: {payload}"
        self.aworset.add(content, [vuln_type, "payload"])
        
    def add_note(self, key: str, value: str):
        """Add/update a note (last-writer-wins)"""
        if key not in self.registers:
            self.registers[key] = LWWRegister(key)
        self.registers[key].set(value, self.node_id)
        
    def search(self, query: str) -> List[str]:
        """Search knowledge base"""
        results = []
        
        for elem in self.gset.search(query):
            results.append(elem.content)
            
        for elem in self.aworset.query():
            if query.lower() in elem.content.lower():
                results.append(elem.content)
                
        return results[:20]
    
    def merge(self, other_data: Dict):
        """Merge another node's data"""
        if "gset" in other_data:
            other_gset = GSetCRDT.from_dict(other_data["gset"])
            self.gset.merge(other_gset)
            
        if "registers" in other_data:
            for key, data in other_data["registers"].items():
                if key not in self.registers:
                    self.registers[key] = LWWRegister(key)
                other_reg = LWWRegister(key)
                other_reg.value = LWWElement(
                    value=data["value"],
                    node_id=data["node_id"],
                    timestamp=data["timestamp"],
                    vector_clock={}
                )
                self.registers[key].merge(other_reg)
                
    def export(self) -> str:
        """Export knowledge base as JSON string"""
        data = {
            "node_id": self.node_id,
            "gset": self.gset.to_dict(),
            "registers": {
                k: {"value": r.get(), "node_id": self.node_id, "timestamp": time.time()}
                for k, r in self.registers.items()
                if r.get()
            }
        }
        return json.dumps(data)
    
    def import_json(self, json_str: str):
        """Import from JSON string"""
        data = json.loads(json_str)
        self.merge(data)

def create_initial_knowledge() -> CRDTKnowledgeBase:
    """Create knowledge base with initial pentesting data"""
    kb = CRDTKnowledgeBase("payloads-bot")
    
    vulnerabilities = [
        ("SQL Injection", "Code injection exploiting database queries", ["injection", "web"]),
        ("XSS", "Cross-site scripting - inject malicious scripts", ["injection", "web"]),
        ("Buffer Overflow", "Memory overflow writing beyond buffer", ["memory", "binary"]),
        ("Command Injection", "OS command execution via input", ["injection", "system"]),
        ("CSRF", "Cross-site request forgery", ["web", "auth"]),
        ("IDOR", "Insecure direct object reference", ["auth", "access"]),
        ("SSRF", "Server-side request forgery", ["web", "network"]),
    ]
    
    for name, desc, tags in vulnerabilities:
        kb.add_vulnerability(name, desc, tags)
    
    payloads = [
        ("SQL Injection Auth Bypass", "' OR '1'='1", "sql-injection"),
        ("XSS Basic", "<script>alert(1)</script>", "xss"),
        ("Command Injection", "; cat /etc/passwd", "command-injection"),
    ]
    
    for name, payload, vuln_type in payloads:
        kb.add_payload(name, payload, vuln_type)
    
    kb.add_note("cheatsheet", "SQLi: admin'-- | XSS: <script> | BO: A*200 | ROP: gadgets")
    kb.add_note("nmap", "-sV -sC -p- -T4")
    kb.add_note("msfvenom", "windows/meterpreter/reverse_tcp")
    
    logger.info("Created initial knowledge base")
    return kb

def main():
    kb = create_initial_knowledge()
    
    logger.info("Testing search: 'sql'")
    for result in kb.search("sql"):
        print(f"  - {result[:80]}")
    
    logger.info("\nTesting export:")
    exported = kb.export()
    print(f"  Exported {len(exported)} bytes")
    
    logger.info("\nTesting merge simulation:")
    kb2 = CRDTKnowledgeBase("user-2")
    kb2.add_vulnerability("New Vuln", "A new technique", ["new", "test"])
    kb2.add_note("user-note", "User contributions")
    
    print("  Original size:", len(kb.search("")))
    print("  Merged size:", len(kb.search("")))

if __name__ == '__main__':
    main()