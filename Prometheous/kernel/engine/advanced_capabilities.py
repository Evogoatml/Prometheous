"""
Advanced Capabilities for Autonomous Learning Orchestrator
Includes web search, API integrations, and extended actions
"""


import aiohttp
import json
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


class WebSearchCapability:
    """Web search and scraping capabilities"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def search_web(self, query: str, num_results: int = 5) -> List[Dict]:
        """
        Search the web using DuckDuckGo (no API key required)
        Alternative: Use SerpAPI if API key is provided
        """
        if self.api_key:
            return await self._search_serpapi(query, num_results)
        else:
            return await self._search_duckduckgo(query, num_results)
    
    async def _search_duckduckgo(self, query: str, num_results: int) -> List[Dict]:
        """Search using DuckDuckGo HTML"""
        session = await self._get_session()
        
        url = "https://html.duckduckgo.com/html/"
        params = {'q': query}
        
        try:
            async with session.post(url, data=params) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                results = []
                for result in soup.find_all('div', class_='result')[:num_results]:
                    title_elem = result.find('a', class_='result__a')
                    snippet_elem = result.find('a', class_='result__snippet')
                    
                    if title_elem and snippet_elem:
                        results.append({
                            'title': title_elem.get_text(strip=True),
                            'url': title_elem.get('href', ''),
                            'snippet': snippet_elem.get_text(strip=True)
                        })
                
                logger.info(f"Found {len(results)} search results for: {query}")
                return results
        
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []
    
    async def _search_serpapi(self, query: str, num_results: int) -> List[Dict]:
        """Search using SerpAPI"""
        session = await self._get_session()
        
        url = "https://serpapi.com/search"
        params = {
            'q': query,
            'api_key': self.api_key,
            'num': num_results
        }
        
        try:
            async with session.get(url, params=params) as response:
                data = await response.json()
                
                results = []
                for result in data.get('organic_results', []):
                    results.append({
                        'title': result.get('title', ''),
                        'url': result.get('link', ''),
                        'snippet': result.get('snippet', '')
                    })
                
                return results
        
        except Exception as e:
            logger.error(f"SerpAPI search error: {e}")
            return []
    
    async def scrape_url(self, url: str) -> Tuple[bool, str]:
        """Scrape content from a URL"""
        session = await self._get_session()
        
        try:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return False, f"HTTP {response.status}"
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Remove script and style elements
                for script in soup(['script', 'style']):
                    script.decompose()
                
                # Get text
                text = soup.get_text()
                
                # Clean up
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = ' '.join(chunk for chunk in chunks if chunk)
                
                # Limit length
                if len(text) > 10000:
                    text = text[:10000] + "... [truncated]"
                
                logger.info(f"Scraped {len(text)} characters from {url}")
                return True, text
        
        except Exception as e:
            logger.error(f"Scraping error for {url}: {e}")
            return False, str(e)
    
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()


class GitOperations:
    """Git operations for code management"""
    
    @staticmethod
    async def clone_repo(url: str, destination: str) -> Tuple[bool, str]:
        """Clone a git repository"""
        import asyncio
        
        try:
            process = await asyncio.create_subprocess_exec(
                'git', 'clone', url, destination,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            output = stdout.decode() + stderr.decode()
            
            success = process.returncode == 0
            return success, output
        
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    async def commit_changes(repo_path: str, message: str) -> Tuple[bool, str]:
        """Commit changes in a git repository"""
        import asyncio
        
        try:
            # Add all changes
            process = await asyncio.create_subprocess_exec(
                'git', 'add', '.',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            
            # Commit
            process = await asyncio.create_subprocess_exec(
                'git', 'commit', '-m', message,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            output = stdout.decode() + stderr.decode()
            
            success = process.returncode == 0
            return success, output
        
        except Exception as e:
            return False, str(e)


class DataProcessor:
    """Advanced data processing capabilities"""
    
    @staticmethod
    async def parse_json(content: str) -> Tuple[bool, Dict]:
        """Parse JSON safely"""
        try:
            data = json.loads(content)
            return True, data
        except json.JSONDecodeError as e:
            return False, {'error': str(e)}
    
    @staticmethod
    async def parse_csv(content: str) -> Tuple[bool, List[Dict]]:
        """Parse CSV content"""
        import csv
        from io import StringIO
        
        try:
            reader = csv.DictReader(StringIO(content))
            data = list(reader)
            return True, data
        except Exception as e:
            return False, [{'error': str(e)}]
    
    @staticmethod
    async def extract_code_blocks(text: str) -> List[Dict]:
        """Extract code blocks from markdown text"""
        pattern = r'```(\w+)?\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)
        
        blocks = []
        for language, code in matches:
            blocks.append({
                'language': language or 'unknown',
                'code': code.strip()
            })
        
        return blocks
    
    @staticmethod
    async def summarize_text(text: str, max_length: int = 500) -> str:
        """Simple text summarization by extracting key sentences"""
        sentences = text.split('.')
        
        if len(text) <= max_length:
            return text
        
        # Take first few and last few sentences
        num_sentences = max(3, max_length // 100)
        summary_sentences = sentences[:num_sentences] + ['...'] + sentences[-2:]
        
        return '. '.join(s.strip() for s in summary_sentences if s.strip())


class APIIntegrations:
    """Third-party API integrations"""
    
    def __init__(self):
        self.session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def make_request(
        self,
        url: str,
        method: str = 'GET',
        headers: Optional[Dict] = None,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Tuple[bool, Dict]:
        """Make HTTP request to API"""
        session = await self._get_session()
        
        try:
            async with session.request(
                method,
                url,
                headers=headers,
                json=data,
                params=params,
                timeout=30
            ) as response:
                result = await response.json()
                success = 200 <= response.status < 300
                
                return success, result
        
        except Exception as e:
            logger.error(f"API request error: {e}")
            return False, {'error': str(e)}
    
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()


class AdvancedCapabilities:
    """Wrapper for all advanced capabilities"""
    
    def __init__(self, web_search_api_key: Optional[str] = None):
        self.web_search = WebSearchCapability(api_key=web_search_api_key)
        self.git = GitOperations()
        self.data_processor = DataProcessor()
        self.api = APIIntegrations()
    
    async def execute_advanced_action(self, action_type: str, parameters: Dict) -> Tuple[bool, str]:
        """Execute advanced action"""
        try:
            if action_type == 'web_search':
                results = await self.web_search.search_web(
                    parameters.get('query', ''),
                    parameters.get('num_results', 5)
                )
                return True, json.dumps(results, indent=2)
            
            elif action_type == 'web_scrape':
                return await self.web_search.scrape_url(parameters.get('url', ''))
            
            elif action_type == 'git_clone':
                return await self.git.clone_repo(
                    parameters.get('url', ''),
                    parameters.get('destination', '')
                )
            
            elif action_type == 'git_commit':
                return await self.git.commit_changes(
                    parameters.get('repo_path', ''),
                    parameters.get('message', 'Auto commit')
                )
            
            elif action_type == 'parse_json':
                success, data = await self.data_processor.parse_json(
                    parameters.get('content', '')
                )
                return success, json.dumps(data, indent=2)
            
            elif action_type == 'parse_csv':
                success, data = await self.data_processor.parse_csv(
                    parameters.get('content', '')
                )
                return success, json.dumps(data, indent=2)
            
            elif action_type == 'api_request':
                success, data = await self.api.make_request(
                    url=parameters.get('url', ''),
                    method=parameters.get('method', 'GET'),
                    headers=parameters.get('headers'),
                    data=parameters.get('data'),
                    params=parameters.get('params')
                )
                return success, json.dumps(data, indent=2)
            
            else:
                return False, f"Unknown advanced action: {action_type}"
        
        except Exception as e:
            logger.error(f"Advanced action error: {e}")
            return False, str(e)
    
    async def close(self):
        """Clean up resources"""
        await self.web_search.close()
        await self.api.close()


# Integration with main orchestrator
def extend_orchestrator_with_advanced_capabilities(orchestrator, web_search_api_key: Optional[str] = None):
    """
    Add advanced capabilities to an existing orchestrator
    Usage:
        orchestrator = AutonomousOrchestrator(config)
        extend_orchestrator_with_advanced_capabilities(orchestrator)
    """
    advanced = AdvancedCapabilities(web_search_api_key)
    
    # Store reference
    orchestrator.advanced = advanced
    
    # Extend execute_action in ReActEngine
    original_execute = orchestrator.react.execute_action
    
    async def extended_execute(action):
        action_type = action.action_type
        
        # Check if it's an advanced action
        if action_type in ['web_search', 'web_scrape', 'git_clone', 'git_commit',
                          'parse_json', 'parse_csv', 'api_request']:
            return await advanced.execute_advanced_action(action_type, action.parameters)
        
        # Otherwise use original
        return await original_execute(action)
    
    # Replace method
    orchestrator.react.execute_action = extended_execute
    
    logger.info("Extended orchestrator with advanced capabilities")
    
    return orchestrator


if __name__ == '__main__':
    import asyncio
    
    async def test():
        """Test advanced capabilities"""
        advanced = AdvancedCapabilities()
        
        # Test web search
        print("Testing web search...")
        results = await advanced.web_search.search_web("Python programming", 3)
        print(f"Found {len(results)} results")
        
        # Test scraping
        if results:
            print("\nTesting web scraping...")
            success, content = await advanced.web_search.scrape_url(results[0]['url'])
            print(f"Scraped: {len(content)} characters")
        
        await advanced.close()
    
    asyncio.run(test())
