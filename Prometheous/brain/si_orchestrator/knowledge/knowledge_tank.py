"""
Algorithm Knowledge Tank - Backend Information Storage
Indexes and serves algorithm files for Prometheous agents.
"""

from __future__ import annotations

import os
import json
import sqlite3
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import re

@dataclass
class AlgorithmMetadata:
    """Metadata for a single algorithm"""
    id: str
    name: str
    path: str
    category: str
    subcategory: str
    file_type: str
    size: int
    description: str
    tags: List[str]
    dependencies: List[str]
    complexity: Optional[str] = None
    use_cases: Optional[List[str]] = None
    indexed_at: Optional[str] = None
    
    def to_dict(self):
        return asdict(self)

class AlgorithmScanner:
    """Scans and indexes algorithm files"""
    
    # Category detection patterns
    CATEGORIES = {
        'cryptography': ['cipher', 'encrypt', 'decrypt', 'crypto', 'rsa', 'aes'],
        'machine_learning': ['ml', 'neural', 'train', 'model', 'regression', 'classification'],
        'graphs': ['graph', 'dijkstra', 'bfs', 'dfs', 'tree', 'path'],
        'data_structures': ['array', 'linked', 'stack', 'queue', 'heap', 'trie'],
        'dynamic_programming': ['dp', 'knapsack', 'fibonacci', 'memo'],
        'mathematics': ['prime', 'factorial', 'gcd', 'lcm', 'math'],
        'sorting': ['sort', 'merge', 'quick', 'bubble', 'heap'],
        'searching': ['search', 'binary', 'linear'],
        'hashing': ['hash', 'md5', 'sha'],
        'image_processing': ['image', 'pixel', 'filter', 'compression'],
        'network': ['socket', 'tcp', 'udp', 'http', 'ftp']
    }
    
    def __init__(self, base_path: str | Path | None = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        
    def scan_file(self, filepath: Path) -> Optional[AlgorithmMetadata]:
        """Scan single file and extract metadata"""
        try:
            relative_path = filepath.relative_to(self.base_path)
            
            # Extract category from directory structure
            parts = relative_path.parts
            category = parts[0] if len(parts) > 0 else "general"
            subcategory = parts[1] if len(parts) > 1 else "general"
            
            # Generate unique ID
            algo_id = hashlib.md5(str(relative_path).encode()).hexdigest()[:12]
            
            # Extract description from file
            description = self._extract_description(filepath)
            
            # Detect tags
            tags = self._detect_tags(filepath, description)
            
            # Extract dependencies
            dependencies = self._extract_imports(filepath)
            
            # Get file stats
            stat = filepath.stat()
            
            return AlgorithmMetadata(
                id=algo_id,
                name=filepath.stem,
                path=str(relative_path),
                category=category,
                subcategory=subcategory,
                file_type=filepath.suffix,
                size=stat.st_size,
                description=description,
                tags=tags,
                dependencies=dependencies,
                indexed_at=datetime.now().isoformat()
            )
        except Exception as e:
            print(f"Error scanning {filepath}: {e}")
            return None
    
    def _extract_description(self, filepath: Path) -> str:
        """Extract description from file docstring or comments"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(2000)  # First 2000 chars
                
                ext = filepath.suffix
                
                # Python - docstrings
                if ext == '.py':
                    docstring_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
                    if docstring_match:
                        return docstring_match.group(1).strip()[:500]
                    
                    comment_match = re.search(r'#\s+(.*?)(?:\n\n|\n[^#])', content, re.DOTALL)
                    if comment_match:
                        return comment_match.group(1).strip()[:500]
                
                # C#, Java, C++, JavaScript - // or /* */ comments
                elif ext in ['.cs', '.java', '.cpp', '.c', '.js', '.go', '.rs']:
                    # Multi-line comment
                    comment_match = re.search(r'/\*(.*?)\*/', content, re.DOTALL)
                    if comment_match:
                        return comment_match.group(1).strip()[:500]
                    
                    # Single-line comments
                    comment_match = re.search(r'//\s+(.*?)(?:\n\n|\n[^/])', content, re.DOTALL)
                    if comment_match:
                        return comment_match.group(1).strip()[:500]
                
                # Ruby, PHP - # comments
                elif ext in ['.rb', '.php']:
                    comment_match = re.search(r'#\s+(.*?)(?:\n\n|\n[^#])', content, re.DOTALL)
                    if comment_match:
                        return comment_match.group(1).strip()[:500]
                
                return filepath.stem.replace('_', ' ').replace('-', ' ').title()
        except:
            return filepath.stem.replace('_', ' ').replace('-', ' ').title()
    
    def _detect_tags(self, filepath: Path, description: str) -> List[str]:
        """Detect relevant tags from filename and content"""
        tags = set()
        
        text = (filepath.stem + " " + description).lower()
        
        for category, keywords in self.CATEGORIES.items():
            if any(kw in text for kw in keywords):
                tags.add(category)
        
        return list(tags)
    
    def _extract_imports(self, filepath: Path) -> List[str]:
        """Extract imports/dependencies from file"""
        deps = set()
        ext = filepath.suffix
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # Python imports
                if ext == '.py':
                    for line in content.split('\n'):
                        line = line.strip()
                        if line.startswith('import ') or line.startswith('from '):
                            match = re.match(r'(?:from|import)\s+([a-zA-Z0-9_\.]+)', line)
                            if match:
                                module = match.group(1).split('.')[0]
                                deps.add(module)
                
                # C# using statements
                elif ext == '.cs':
                    for match in re.finditer(r'using\s+([a-zA-Z0-9_\.]+);', content):
                        deps.add(match.group(1).split('.')[0])
                
                # JavaScript/Node imports
                elif ext == '.js':
                    for match in re.finditer(r'(?:import|require)\s*\(?[\'"]([a-zA-Z0-9_\-@/]+)', content):
                        deps.add(match.group(1).split('/')[0])
                
                # Java imports
                elif ext == '.java':
                    for match in re.finditer(r'import\s+([a-zA-Z0-9_\.]+);', content):
                        deps.add(match.group(1).split('.')[0])
                
                # C/C++ includes
                elif ext in ['.c', '.cpp', '.h', '.hpp']:
                    for match in re.finditer(r'#include\s+[<"]([a-zA-Z0-9_\.]+)', content):
                        deps.add(match.group(1))
        except:
            pass
        
        return list(deps)
    
    def scan_directory(self, max_files: Optional[int] = None) -> List[AlgorithmMetadata]:
        """Scan entire algorithm directory"""
        algorithms = []
        count = 0
        
        # File extensions to index
        extensions = {'.py', '.cs', '.js', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.php'}
        
        print(f"Scanning {self.base_path}...")
        
        for root, dirs, files in os.walk(self.base_path):
            # Skip common non-algorithm directories
            dirs[:] = [d for d in dirs if d not in ['__pycache__', 'node_modules', '.git', 'bin', 'obj']]
            
            for filename in files:
                # Check if it's an algorithm file
                if any(filename.endswith(ext) for ext in extensions) and not filename.startswith('__'):
                    filepath = Path(root) / filename
                    
                    metadata = self.scan_file(filepath)
                    if metadata:
                        algorithms.append(metadata)
                        count += 1
                        
                        if count % 100 == 0:
                            print(f"  Indexed {count} algorithms...")
                        
                        if max_files and count >= max_files:
                            print(f"Reached max files limit: {max_files}")
                            return algorithms
        
        print(f"✓ Scanned {count} algorithms")
        return algorithms

class KnowledgeTank:
    """Backend storage for algorithm knowledge"""
    
    def __init__(self, db_path: str | Path | None = None):
        root = Path(__file__).resolve().parents[4]
        self.db_path = str(Path(db_path) if db_path else root / "data" / "knowledge_tank.db")
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create algorithms table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS algorithms (
                id TEXT PRIMARY KEY,
                name TEXT,
                path TEXT UNIQUE,
                category TEXT,
                subcategory TEXT,
                file_type TEXT,
                size INTEGER,
                description TEXT,
                tags TEXT,
                dependencies TEXT,
                complexity TEXT,
                use_cases TEXT,
                indexed_at TEXT
            )
        ''')
        
        # Create search index
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_category ON algorithms(category)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tags ON algorithms(tags)
        ''')
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS algorithms_fts 
            USING fts5(name, description, tags, content=algorithms)
        ''')
        
        conn.commit()
        conn.close()
        print(f"✓ Knowledge Tank initialized: {self.db_path}")
    
    def index_algorithm(self, algo: AlgorithmMetadata):
        """Add algorithm to knowledge tank"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO algorithms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            algo.id,
            algo.name,
            algo.path,
            algo.category,
            algo.subcategory,
            algo.file_type,
            algo.size,
            algo.description,
            json.dumps(algo.tags),
            json.dumps(algo.dependencies),
            algo.complexity,
            json.dumps(algo.use_cases) if algo.use_cases else None,
            algo.indexed_at
        ))
        
        # Update FTS index
        cursor.execute('''
            INSERT OR REPLACE INTO algorithms_fts(rowid, name, description, tags)
            SELECT rowid, name, description, tags FROM algorithms WHERE id = ?
        ''', (algo.id,))
        
        conn.commit()
        conn.close()
    
    def index_batch(self, algorithms: List[AlgorithmMetadata]):
        """Bulk index algorithms"""
        print(f"Indexing {len(algorithms)} algorithms...")
        
        for i, algo in enumerate(algorithms):
            self.index_algorithm(algo)
            if (i + 1) % 1000 == 0:
                print(f"  Indexed {i + 1}/{len(algorithms)}")
        
        print(f"✓ Indexed {len(algorithms)} algorithms")
    
    def search(self, query: str, category: Optional[str] = None, 
               limit: int = 10) -> List[Dict]:
        """Search algorithms by query"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            # Category-filtered search
            cursor.execute('''
                SELECT a.* FROM algorithms a
                JOIN algorithms_fts fts ON a.rowid = fts.rowid
                WHERE algorithms_fts MATCH ? AND a.category = ?
                LIMIT ?
            ''', (query, category, limit))
        else:
            # Full-text search
            cursor.execute('''
                SELECT a.* FROM algorithms a
                JOIN algorithms_fts fts ON a.rowid = fts.rowid
                WHERE algorithms_fts MATCH ?
                LIMIT ?
            ''', (query, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'id': row[0],
                'name': row[1],
                'path': row[2],
                'category': row[3],
                'subcategory': row[4],
                'description': row[7],
                'tags': json.loads(row[8]) if row[8] else []
            })
        
        conn.close()
        return results
    
    def get_by_category(self, category: str, limit: int = 100) -> List[Dict]:
        """Get all algorithms in a category"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, path, category, subcategory, description, tags
            FROM algorithms WHERE category = ? LIMIT ?
        ''', (category, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'id': row[0],
                'name': row[1],
                'path': row[2],
                'category': row[3],
                'subcategory': row[4],
                'description': row[5],
                'tags': json.loads(row[6]) if row[6] else []
            })
        
        conn.close()
        return results
    
    def get_by_id(self, algo_id: str) -> Optional[Dict]:
        """Get algorithm by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM algorithms WHERE id = ?', (algo_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'id': row[0],
            'name': row[1],
            'path': row[2],
            'category': row[3],
            'subcategory': row[4],
            'file_type': row[5],
            'size': row[6],
            'description': row[7],
            'tags': json.loads(row[8]) if row[8] else [],
            'dependencies': json.loads(row[9]) if row[9] else []
        }
    
    def get_stats(self) -> Dict:
        """Get knowledge tank statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total count
        cursor.execute('SELECT COUNT(*) FROM algorithms')
        total = cursor.fetchone()[0]
        
        # By category
        cursor.execute('''
            SELECT category, COUNT(*) 
            FROM algorithms 
            GROUP BY category 
            ORDER BY COUNT(*) DESC
        ''')
        by_category = {row[0]: row[1] for row in cursor.fetchall()}
        
        # By file type
        cursor.execute('''
            SELECT file_type, COUNT(*) 
            FROM algorithms 
            GROUP BY file_type
        ''')
        by_type = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'total_algorithms': total,
            'by_category': by_category,
            'by_file_type': by_type
        }
    
    def export_to_json(self, output_path: str):
        """Export entire knowledge base to JSON"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM algorithms')
        
        algorithms = []
        for row in cursor.fetchall():
            algorithms.append({
                'id': row[0],
                'name': row[1],
                'path': row[2],
                'category': row[3],
                'subcategory': row[4],
                'file_type': row[5],
                'size': row[6],
                'description': row[7],
                'tags': json.loads(row[8]) if row[8] else [],
                'dependencies': json.loads(row[9]) if row[9] else []
            })
        
        conn.close()
        
        with open(output_path, 'w') as f:
            json.dump(algorithms, f, indent=2)
        
        print(f"✓ Exported {len(algorithms)} algorithms to {output_path}")

# Build the knowledge tank
if __name__ == "__main__":
    print("=== Building Algorithm Knowledge Tank ===\n")
    
    # Scan algorithms
    scanner = AlgorithmScanner()
    algorithms = scanner.scan_directory(max_files=None)  # Set to None for all files
    
    # Index into knowledge tank
    tank = KnowledgeTank()
    tank.index_batch(algorithms)
    
    # Show stats
    print("\n=== Knowledge Tank Stats ===")
    stats = tank.get_stats()
    print(f"Total Algorithms: {stats['total_algorithms']}")
    print("\nBy Category:")
    for cat, count in sorted(stats['by_category'].items(), key=lambda x: -x[1])[:10]:
        print(f"  {cat}: {count}")
    
    # Test search
    print("\n=== Testing Search ===")
    results = tank.search("encryption rsa")
    print(f"Found {len(results)} results for 'encryption rsa':")
    for r in results[:5]:
        print(f"  - {r['name']} ({r['category']})")
    
    # Export
    # tank.export_to_json("/home/chewlo/GhostGoat/knowledge_export.json")
    
    print("\n✓ Knowledge Tank ready!")

