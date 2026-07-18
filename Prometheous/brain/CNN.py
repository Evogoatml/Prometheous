"""
Distributed Agent System with Central Neural Network
- One centralized .backend neural network
- Auto-generates AGENT.md in every root folder
- Each AGENT.md auto-populates with its folder's context
- All agents share the same neural backend
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import pickle

class CentralNeuralBackend:
    """Central neural network - single source of truth"""
    
    def __init__(self, root_dir=None):
        self.root_dir = root_dir or os.getcwd()
        self.backend_dir = os.path.join(self.root_dir, '.backend')
        
        # Central storage
        self.graph_db = os.path.join(self.backend_dir, 'knowledge_graph.pkl')
        self.registry_db = os.path.join(self.backend_dir, 'file_registry.json')
        self.agents_db = os.path.join(self.backend_dir, 'agents.json')
        
        # Neural state
        self.knowledge_graph = {}
        self.file_registry = {}
        self.agent_registry = {}  # Track all AGENT.md files
        
        self._initialize()
    
    def _initialize(self):
        """Initialize central backend"""
        os.makedirs(self.backend_dir, exist_ok=True)
        os.makedirs(os.path.join(self.backend_dir, 'agents'), exist_ok=True)
        
        self._load_state()
        print(f"✓ Central neural backend: {self.backend_dir}")
    
    def _load_state(self):
        """Load neural network state"""
        if os.path.exists(self.graph_db):
            with open(self.graph_db, 'rb') as f:
                self.knowledge_graph = pickle.load(f)
        
        if os.path.exists(self.registry_db):
            with open(self.registry_db, 'r') as f:
                self.file_registry = json.load(f)
        
        if os.path.exists(self.agents_db):
            with open(self.agents_db, 'r') as f:
                self.agent_registry = json.load(f)
    
    def _save_state(self):
        """Save neural network state"""
        with open(self.graph_db, 'wb') as f:
            pickle.dump(self.knowledge_graph, f)
        
        with open(self.registry_db, 'w') as f:
            json.dump(self.file_registry, f, indent=2)
        
        with open(self.agents_db, 'w') as f:
            json.dump(self.agent_registry, f, indent=2)
    
    def register_agent(self, folder_path, agent_path):
        """Register a new agent in the system"""
        agent_id = hashlib.md5(folder_path.encode()).hexdigest()[:8]
        
        self.agent_registry[agent_id] = {
            'folder': folder_path,
            'agent_file': agent_path,
            'created': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
        
        self._save_state()
        return agent_id
    
    def get_folder_context(self, folder_path):
        """Get all files and metadata for a specific folder"""
        folder_files = {}
        
        for filepath, metadata in self.file_registry.items():
            if filepath.startswith(folder_path):
                rel_path = os.path.relpath(filepath, folder_path)
                folder_files[rel_path] = metadata
        
        return folder_files
    
    def index_file(self, filepath):
        """Index a file into the neural network"""
        try:
            stat = os.stat(filepath)
            
            metadata = {
                'path': filepath,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'extension': Path(filepath).suffix,
                'hash': self._calculate_hash(filepath)
            }
            
            self.file_registry[filepath] = metadata
            self.knowledge_graph[filepath] = {
                'metadata': metadata,
                'indexed_at': datetime.now().isoformat()
            }
            
            self._save_state()
            
        except Exception as e:
            print(f"⚠ Error indexing {filepath}: {e}")
    
    def _calculate_hash(self, filepath):
        """Calculate file hash"""
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                hasher.update(f.read())
            return hasher.hexdigest()
        except:
            return None


class FolderAgent:
    """Agent for a specific folder - auto-populates AGENT.md"""
    
    def __init__(self, folder_path, neural_backend):
        self.folder_path = folder_path
        self.backend = neural_backend
        self.agent_file = os.path.join(folder_path, 'AGENT.md')
        self.agent_id = None
    
    def generate_agent_file(self):
        """Auto-populate AGENT.md with folder context"""
        
        # Get folder context from neural backend
        folder_files = self.backend.get_folder_context(self.folder_path)
        
        # Generate agent content
        agent_content = self._build_agent_content(folder_files)
        
        # Write AGENT.md
        with open(self.agent_file, 'w') as f:
            f.write(agent_content)
        
        # Register with central backend
        self.agent_id = self.backend.register_agent(self.folder_path, self.agent_file)
        
        print(f"✓ Generated: {self.agent_file} (Agent ID: {self.agent_id})")
    
    def _build_agent_content(self, folder_files):
        """Build the AGENT.md content"""
        
        folder_name = os.path.basename(self.folder_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        content = f"""# 🤖 AGENT - {folder_name}

**Auto-generated folder agent**  
**Last Updated:** {timestamp}  
**Folder Path:** `{self.folder_path}`  
**Agent ID:** `{self.agent_id or 'pending'}`

---

## 📁 Folder Context

This agent maintains awareness of all files in this folder and connects to the central neural network at `.backend/`

### Files Tracked ({len(folder_files)})

"""
        
        # Group files by extension
        files_by_ext = defaultdict(list)
        for rel_path, metadata in folder_files.items():
            ext = metadata.get('extension', 'no extension')
            files_by_ext[ext].append((rel_path, metadata))
        
        # List files organized by type
        for ext, files in sorted(files_by_ext.items()):
            content += f"\n#### {ext if ext else 'No Extension'} Files ({len(files)})\n\n"
            
            for rel_path, metadata in sorted(files):
                size = metadata.get('size', 0)
                size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
                modified = metadata.get('modified', 'unknown')[:10]
                
                content += f"- `{rel_path}`\n"
                content += f"  - Size: {size_str}\n"
                content += f"  - Modified: {modified}\n"
        
        # Add statistics
        total_size = sum(m.get('size', 0) for m in folder_files.values())
        total_size_str = f"{total_size / 1024 / 1024:.2f}MB" if total_size > 1024*1024 else f"{total_size / 1024:.1f}KB"
        
        content += f"""

---

## 📊 Statistics

- **Total Files:** {len(folder_files)}
- **Total Size:** {total_size_str}
- **File Types:** {len(files_by_ext)}

---

## 🔗 Neural Network Connection

This agent is connected to the central neural backend:
- **Backend Path:** `.backend/`
- **Knowledge Graph:** Shared across all agents
- **Agent Registry:** `.backend/agents.json`

### Query This Agent

```python
# Other scripts can query this folder's context
from .backend.ordinance_api import OrdinanceClient

client = OrdinanceClient()
context = client.get_folder_context('{self.folder_path}')
```

---

## 🧠 Purpose

This AGENT.md file provides:
1. **Folder Awareness** - Know what files exist here
2. **Context for AI** - Help AI understand this folder's purpose
3. **Navigation** - Quick reference for developers
4. **Neural Link** - Connection to central knowledge graph

**Note:** This file is auto-generated. Do not edit manually - it will be overwritten.

---

*Generated by Central Neural Ordinance System*  
*Last scan: {timestamp}*
"""
        
        return content
    
    def update_agent_file(self):
        """Update existing AGENT.md with latest context"""
        self.generate_agent_file()


class DistributedAgentSystem:
    """Main system - creates agents in every root folder"""
    
    def __init__(self, root_dir=None):
        self.root_dir = root_dir or os.getcwd()
        self.backend = CentralNeuralBackend(self.root_dir)
        self.agents = []
    
    def scan_and_generate_agents(self, exclude_dirs=None, extensions=None):
        """Scan all folders and generate AGENT.md files"""
        
        if exclude_dirs is None:
            exclude_dirs = {'.git', '.backend', '__pycache__', 'node_modules', '.venv', 'venv', '.idea'}
        
        if extensions is None:
            extensions = {'.py', '.js', '.json', '.txt', '.md', '.yaml', '.yml', '.toml', '.csv', '.html', '.css'}
        
        print(f"\n🔍 Scanning from: {self.root_dir}")
        print(f"📝 Generating AGENT.md in every root folder...\n")
        
        # Track folders that need agents
        folders_with_files = set()
        
        # First pass: Index all files into neural backend
        for root, dirs, files in os.walk(self.root_dir):
            # Exclude certain directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for filename in files:
                filepath = os.path.join(root, filename)
                
                # Skip AGENT.md files themselves
                if filename == 'AGENT.md':
                    continue
                
                # Filter by extension
                if extensions and Path(filepath).suffix not in extensions:
                    continue
                
                # Index file
                self.backend.index_file(filepath)
                
                # Mark this folder as needing an agent
                folders_with_files.add(root)
        
        # Second pass: Generate AGENT.md for each folder with files
        agent_count = 0
        for folder in sorted(folders_with_files):
            agent = FolderAgent(folder, self.backend)
            agent.generate_agent_file()
            self.agents.append(agent)
            agent_count += 1
        
        print(f"\n✓ Scan complete!")
        print(f"  - Files indexed: {len(self.backend.file_registry)}")
        print(f"  - Agents created: {agent_count}")
        print(f"  - Central backend: {self.backend.backend_dir}")
    
    def update_all_agents(self):
        """Update all existing AGENT.md files"""
        print("\n🔄 Updating all agents...")
        
        for agent in self.agents:
            agent.update_agent_file()
        
        print(f"✓ Updated {len(self.agents)} agents")
    
    def list_agents(self):
        """List all registered agents"""
        print("\n📋 Registered Agents:\n")
        
        for agent_id, info in self.backend.agent_registry.items():
            folder = info['folder']
            rel_folder = os.path.relpath(folder, self.root_dir)
            print(f"  [{agent_id}] {rel_folder}/")
            print(f"      Agent: {info['agent_file']}")
            print(f"      Updated: {info['last_updated'][:19]}")
            print()


# Run the distributed agent system
if __name__ == "__main__":
    print("=" * 60)
    print("DISTRIBUTED AGENT SYSTEM")
    print("Central Neural Network + Folder Agents")
    print("=" * 60)
    
    system = DistributedAgentSystem()
    
    # Scan and generate agents
    system.scan_and_generate_agents()
    
    # List all agents
    system.list_agents()
    
    print("\n💡 Usage:")
    print("  - Each folder now has AGENT.md with its context")
    print("  - All agents connect to .backend/ neural network")
    print("  - Run this script again to update all agents")
    print("  - No duplication - one central backend!")
