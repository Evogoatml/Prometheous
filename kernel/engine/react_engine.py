# react_engine.py

import os
import asyncio
import time
from typing import Dict, Any
from openai import OpenAI, APIError

# Import the global config object from the separate config file
from config import config

# --- Module-level instance (will be defined at the end) ---
react_engine = None

class ReactEngine:
    """
    Core engine for managing asynchronous calls to the OpenAI API (or other LLMs).
    """
    
    def __init__(self):
        # 1. Get key from config (which loaded it from .env)
        api_key = config.llm.api_key
        if not api_key:
            raise ValueError(f"API key not set for LLM Provider: {config.llm.provider}. Check config.py.")
            
        # 2. Initialize the synchronous OpenAI client
        self.client = OpenAI(api_key=api_key, base_url=config.llm.base_url)
        
        # 3. Define model and system prompt
        self.model = config.llm.model 
        self.system_prompt = (
            "You are the Autonomous Learning Orchestrator (ALO). "
            "Your task is to analyze user requests, reason through necessary steps, "
            "and execute actions. Provide concise, factual responses based on the task outcome."
        )

    async def execute_task(self, prompt: str) -> Dict[str, Any]:
        """
        Executes a task by calling the configured OpenAI model.
        """
        start_time = time.time()
        
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ]

            # CRITICAL FIX: Run synchronous client call in a thread pool
            completion = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens
            )
            
            execution_time = time.time() - start_time
            response_content = completion.choices[0].message.content
            
            return {
                "success": True, 
                "response": response_content,
                "execution_time": execution_time,
                "iterations": 1,
                "history": [{"step": 1, "action": "LLM Call", "result": response_content}]
            }

        except APIError as e:
            execution_time = time.time() - start_time
            return {
                "success": False, 
                "response": f"OpenAI API Error: Code {e.status_code}",
                "error": str(e),
                "execution_time": execution_time,
                "suggestion": "Check logs for detailed API status codes."
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            return {
                "success": False, 
                "response": "An unexpected error occurred during task execution.",
                "error": str(e),
                "execution_time": execution_time,
                "suggestion": "Verify network connection."
            }

# Instantiate the engine globally for import in main.py
try:
    react_engine = ReactEngine()
except ValueError as e:
    # If key is missing, this handles the import error gracefully
    import logging
    logging.getLogger(__name__).critical(str(e))
    react_engine = None 
# react_engine.py

import os
import asyncio
import time
from typing import Dict, Any
from openai import OpenAI, APIError

# Import the global config object from the separate config file
from config import config

# --- Module-level instance (will be defined at the end) ---
react_engine = None

class ReactEngine:
    """
    Core engine for managing asynchronous calls to the OpenAI API (or other LLMs).
    """
    
    def __init__(self):
        # 1. Get key from config (which loaded it from .env)
        api_key = config.llm.api_key
        if not api_key:
            raise ValueError(f"API key not set for LLM Provider: {config.llm.provider}. Check config.py.")
            
        # 2. Initialize the synchronous OpenAI client
        self.client = OpenAI(api_key=api_key, base_url=config.llm.base_url)
        
        # 3. Define model and system prompt
        self.model = config.llm.model 
        self.system_prompt = (
            "You are the Autonomous Learning Orchestrator (ALO). "
            "Your task is to analyze user requests, reason through necessary steps, "
            "and execute actions. Provide concise, factual responses based on the task outcome."
        )

    async def execute_task(self, prompt: str) -> Dict[str, Any]:
        """
        Executes a task by calling the configured OpenAI model.
        """
        start_time = time.time()
        
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ]

            # CRITICAL FIX: Run synchronous client call in a thread pool
            completion = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens
            )
            
            execution_time = time.time() - start_time
            response_content = completion.choices[0].message.content
            
            return {
                "success": True, 
                "response": response_content,
                "execution_time": execution_time,
                "iterations": 1,
                "history": [{"step": 1, "action": "LLM Call", "result": response_content}]
            }

        except APIError as e:
            execution_time = time.time() - start_time
            return {
                "success": False, 
                "response": f"OpenAI API Error: Code {e.status_code}",
                "error": str(e),
                "execution_time": execution_time,
                "suggestion": "Check logs for detailed API status codes."
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            return {
                "success": False, 
                "response": "An unexpected error occurred during task execution.",
                "error": str(e),
                "execution_time": execution_time,
                "suggestion": "Verify network connection."
            }

# Instantiate the engine globally for import in main.py
try:
    react_engine = ReactEngine()
except ValueError as e:
    # If key is missing, this handles the import error gracefully
    import logging
    logging.getLogger(__name__).critical(str(e))
    react_engine = None 

