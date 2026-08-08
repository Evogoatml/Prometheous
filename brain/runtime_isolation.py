#!/usr/bin/env python3
"""
Prometheous runtime isolation and tool sandboxing.

Hardens the ReAct/MCP action layer for Prometheous agents:
  - Capability-based tool access
  - Threat-level policies (SAFE → CRITICAL)
  - Docker / namespace / seccomp / process fallbacks
  - Audit logging and anomaly detection

Entry point: kernel.sandbox.get_sandbox_gate()
"""

import os
import sys
import json
import subprocess
import tempfile
import shutil
import hashlib
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
import resource
import signal


logger = logging.getLogger(__name__)


class ThreatLevel(Enum):
    """Threat levels for different operations"""
    SAFE = 1        # Read-only, no system access
    LOW = 2         # Limited file access, no network
    MEDIUM = 3      # File write, limited network
    HIGH = 4        # System commands, full network
    CRITICAL = 5    # Kernel access, unrestricted


class IsolationMethod(Enum):
    """Available isolation methods"""
    DOCKER = "docker"
    GVISOR = "gvisor"
    FIRECRACKER = "firecracker"
    NAMESPACE = "namespace"
    SECCOMP = "seccomp"


@dataclass
class SecurityPolicy:
    """Security policy for sandbox execution"""
    allowed_syscalls: List[str] = field(default_factory=list)
    blocked_syscalls: List[str] = field(default_factory=list)
    max_memory_mb: int = 512
    max_cpu_percent: int = 50
    max_execution_time: int = 30  # seconds
    max_file_size_mb: int = 100
    allowed_read_paths: List[str] = field(default_factory=list)
    allowed_write_paths: List[str] = field(default_factory=list)
    network_enabled: bool = False
    network_whitelist: List[str] = field(default_factory=list)
    allow_process_spawn: bool = False
    max_processes: int = 10
    threat_level: ThreatLevel = ThreatLevel.MEDIUM
    
    def to_dict(self) -> Dict:
        """Serialize policy to dict"""
        return {
            'allowed_syscalls': self.allowed_syscalls,
            'blocked_syscalls': self.blocked_syscalls,
            'max_memory_mb': self.max_memory_mb,
            'max_cpu_percent': self.max_cpu_percent,
            'max_execution_time': self.max_execution_time,
            'max_file_size_mb': self.max_file_size_mb,
            'allowed_read_paths': self.allowed_read_paths,
            'allowed_write_paths': self.allowed_write_paths,
            'network_enabled': self.network_enabled,
            'network_whitelist': self.network_whitelist,
            'allow_process_spawn': self.allow_process_spawn,
            'max_processes': self.max_processes,
            'threat_level': self.threat_level.name
        }


@dataclass
class ExecutionResult:
    """Result of sandboxed execution"""
    success: bool
    output: str
    error: str
    exit_code: int
    execution_time: float
    memory_used_mb: float
    policy_violations: List[str] = field(default_factory=list)
    security_events: List[Dict] = field(default_factory=list)


class SecurityPolicyFactory:
    """Factory for creating security policies based on threat level"""
    
    @staticmethod
    def get_policy(threat_level: ThreatLevel) -> SecurityPolicy:
        """Get appropriate security policy for threat level"""
        
        if threat_level == ThreatLevel.SAFE:
            return SecurityPolicy(
                # Minimal syscalls for read-only operations
                allowed_syscalls=[
                    'read', 'write', 'open', 'close', 'stat', 'fstat',
                    'lseek', 'mmap', 'mprotect', 'munmap', 'brk',
                    'rt_sigaction', 'rt_sigprocmask', 'rt_sigreturn',
                    'ioctl', 'access', 'select', 'clone', 'execve',
                    'wait4', 'exit', 'exit_group'
                ],
                max_memory_mb=256,
                max_cpu_percent=25,
                max_execution_time=10,
                max_file_size_mb=10,
                network_enabled=False,
                allow_process_spawn=False,
                max_processes=1,
                threat_level=ThreatLevel.SAFE
            )
        
        elif threat_level == ThreatLevel.LOW:
            return SecurityPolicy(
                allowed_syscalls=[
                    'read', 'write', 'open', 'close', 'stat', 'fstat',
                    'lseek', 'mmap', 'mprotect', 'munmap', 'brk',
                    'rt_sigaction', 'rt_sigprocmask', 'rt_sigreturn',
                    'ioctl', 'access', 'select', 'clone', 'execve',
                    'wait4', 'exit', 'exit_group', 'getcwd', 'chdir'
                ],
                max_memory_mb=512,
                max_cpu_percent=50,
                max_execution_time=30,
                max_file_size_mb=50,
                allowed_write_paths=['/tmp'],
                network_enabled=False,
                allow_process_spawn=False,
                max_processes=3,
                threat_level=ThreatLevel.LOW
            )
        
        elif threat_level == ThreatLevel.MEDIUM:
            return SecurityPolicy(
                blocked_syscalls=[
                    'ptrace', 'reboot', 'swapon', 'swapoff',
                    'mount', 'umount', 'pivot_root', 'chroot',
                    'acct', 'settimeofday', 'stime', 'adjtimex',
                    'init_module', 'delete_module', 'ioperm', 'iopl'
                ],
                max_memory_mb=1024,
                max_cpu_percent=75,
                max_execution_time=60,
                max_file_size_mb=100,
                allowed_write_paths=['/tmp', '/workspace'],
                network_enabled=True,
                network_whitelist=['api.anthropic.com', 'pypi.org', 'github.com'],
                allow_process_spawn=True,
                max_processes=10,
                threat_level=ThreatLevel.MEDIUM
            )
        
        elif threat_level == ThreatLevel.HIGH:
            return SecurityPolicy(
                blocked_syscalls=[
                    'ptrace', 'reboot', 'swapon', 'swapoff',
                    'init_module', 'delete_module', 'ioperm', 'iopl'
                ],
                max_memory_mb=2048,
                max_cpu_percent=90,
                max_execution_time=300,
                max_file_size_mb=500,
                network_enabled=True,
                allow_process_spawn=True,
                max_processes=50,
                threat_level=ThreatLevel.HIGH
            )
        
        else:  # CRITICAL
            logger.warning("CRITICAL threat level - minimal restrictions")
            return SecurityPolicy(
                max_memory_mb=4096,
                max_cpu_percent=100,
                max_execution_time=600,
                network_enabled=True,
                allow_process_spawn=True,
                max_processes=100,
                threat_level=ThreatLevel.CRITICAL
            )


class SandboxExecutor:
    """
    Base class for sandboxed execution
    Provides runtime isolation for AI agent actions
    """
    
    def __init__(self, policy: SecurityPolicy, isolation_method: IsolationMethod):
        self.policy = policy
        self.isolation_method = isolation_method
        self.audit_log = []
        
    def execute(self, command: str, **kwargs) -> ExecutionResult:
        """Execute command in sandbox - must be implemented by subclass"""
        raise NotImplementedError
    
    def _log_security_event(self, event_type: str, details: Dict):
        """Log security-relevant event"""
        event = {
            'timestamp': time.time(),
            'type': event_type,
            'details': details,
            'threat_level': self.policy.threat_level.name
        }
        self.audit_log.append(event)
        logger.warning(f"Security Event: {event_type} - {details}")
    
    def _check_resource_limits(self, process) -> List[str]:
        """Check if process exceeds resource limits"""
        violations = []
        
        # Check memory usage
        try:
            import psutil
            proc = psutil.Process(process.pid)
            memory_mb = proc.memory_info().rss / (1024 * 1024)
            
            if memory_mb > self.policy.max_memory_mb:
                violations.append(f"Memory limit exceeded: {memory_mb:.2f}MB > {self.policy.max_memory_mb}MB")
        except:
            pass
        
        return violations


class DockerSandbox(SandboxExecutor):
    """
    Docker-based sandbox execution
    Provides strong isolation with container technology
    """
    
    def __init__(self, policy: SecurityPolicy):
        super().__init__(policy, IsolationMethod.DOCKER)
        self.image = "python:3.11-alpine"
        
    def execute(self, command: str, working_dir: str = "/workspace",
                env: Dict[str, str] = None) -> ExecutionResult:
        """Execute command in Docker container"""
        
        start_time = time.time()
        violations = []
        security_events = []
        
        # Build Docker run command
        docker_cmd = [
            'docker', 'run',
            '--rm',
            '--read-only',  # Read-only filesystem
            '--tmpfs', '/tmp',  # Writable tmp
            '--memory', f'{self.policy.max_memory_mb}m',
            '--cpus', str(self.policy.max_cpu_percent / 100.0),
            '--pids-limit', str(self.policy.max_processes),
        ]
        
        # Network isolation
        if not self.policy.network_enabled:
            docker_cmd.extend(['--network', 'none'])
        
        # Add volume mounts
        if self.policy.allowed_write_paths:
            temp_workspace = tempfile.mkdtemp()
            docker_cmd.extend(['-v', f'{temp_workspace}:{working_dir}'])
        
        # Add security options
        docker_cmd.extend(['--security-opt', 'no-new-privileges', '--cap-drop', 'ALL'])
        if self.policy.network_enabled:
            docker_cmd.extend(['--cap-add', 'NET_BIND_SERVICE'])
        
        # Set working directory
        docker_cmd.extend(['-w', working_dir])
        
        # Add environment variables
        if env:
            for key, value in env.items():
                docker_cmd.extend(['-e', f'{key}={value}'])
        
        # Add image and command
        docker_cmd.append(self.image)
        docker_cmd.extend(['sh', '-c', command])
        
        # Remove empty strings
        docker_cmd = [x for x in docker_cmd if x]
        
        # Execute with timeout
        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.policy.max_execution_time
            )
            
            execution_time = time.time() - start_time
            
            # Check for policy violations
            if result.returncode != 0 and 'permission denied' in result.stderr.lower():
                violations.append("Permission denied - attempted restricted operation")
                self._log_security_event('PERMISSION_DENIED', {'command': command})
            
            return ExecutionResult(
                success=(result.returncode == 0),
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
                execution_time=execution_time,
                memory_used_mb=0,  # Docker doesn't easily report this
                policy_violations=violations,
                security_events=security_events
            )
            
        except subprocess.TimeoutExpired:
            violations.append(f"Execution timeout: {self.policy.max_execution_time}s exceeded")
            self._log_security_event('TIMEOUT', {
                'command': command,
                'timeout': self.policy.max_execution_time
            })
            
            return ExecutionResult(
                success=False,
                output="",
                error=f"Execution timeout after {self.policy.max_execution_time}s",
                exit_code=-1,
                execution_time=self.policy.max_execution_time,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=security_events
            )
        
        except Exception as e:
            self._log_security_event('EXECUTION_ERROR', {
                'command': command,
                'error': str(e)
            })
            
            return ExecutionResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
                execution_time=time.time() - start_time,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=security_events
            )


class NamespaceSandbox(SandboxExecutor):
    """
    Linux namespace-based sandbox
    Lighter weight than Docker, uses native kernel features
    """
    
    def __init__(self, policy: SecurityPolicy):
        super().__init__(policy, IsolationMethod.NAMESPACE)
        
    def execute(self, command: str, working_dir: str = None) -> ExecutionResult:
        """Execute command with Linux namespaces"""
        
        if not working_dir:
            working_dir = tempfile.mkdtemp()
        
        start_time = time.time()
        violations = []
        
        # Use unshare to create new namespaces
        unshare_cmd = [
            'unshare',
            '--map-root-user',  # User namespace
            '--pid',            # PID namespace
            '--mount',          # Mount namespace
            '--ipc',            # IPC namespace
        ]
        
        if not self.policy.network_enabled:
            unshare_cmd.append('--net')  # Network namespace
        
        unshare_cmd.extend(['--', 'sh', '-c', command])
        
        try:
            # Set resource limits
            def set_limits():
                # Memory limit
                resource.setrlimit(
                    resource.RLIMIT_AS,
                    (self.policy.max_memory_mb * 1024 * 1024,
                     self.policy.max_memory_mb * 1024 * 1024)
                )
                
                # CPU time limit
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (self.policy.max_execution_time,
                     self.policy.max_execution_time)
                )
                
                # Process limit
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (self.policy.max_processes,
                     self.policy.max_processes)
                )
            
            result = subprocess.run(
                unshare_cmd,
                capture_output=True,
                text=True,
                timeout=self.policy.max_execution_time,
                cwd=working_dir,
                preexec_fn=set_limits
            )
            
            execution_time = time.time() - start_time
            
            return ExecutionResult(
                success=(result.returncode == 0),
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
                execution_time=execution_time,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=[]
            )
            
        except subprocess.TimeoutExpired:
            violations.append(f"Execution timeout: {self.policy.max_execution_time}s exceeded")
            
            return ExecutionResult(
                success=False,
                output="",
                error=f"Timeout after {self.policy.max_execution_time}s",
                exit_code=-1,
                execution_time=self.policy.max_execution_time,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=[]
            )


class SeccompSandbox(SandboxExecutor):
    """
    Seccomp (Secure Computing Mode) based sandbox
    Filters system calls at kernel level
    """
    
    def __init__(self, policy: SecurityPolicy):
        super().__init__(policy, IsolationMethod.SECCOMP)
        
    def _generate_seccomp_profile(self) -> Dict:
        """Generate seccomp profile from policy"""
        profile = {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64"],
            "syscalls": []
        }
        
        # Allow specified syscalls
        if self.policy.allowed_syscalls:
            profile["syscalls"].append({
                "names": self.policy.allowed_syscalls,
                "action": "SCMP_ACT_ALLOW"
            })
        
        # Block specified syscalls
        if self.policy.blocked_syscalls:
            profile["syscalls"].append({
                "names": self.policy.blocked_syscalls,
                "action": "SCMP_ACT_KILL"
            })
        
        return profile
    
    def execute(self, command: str) -> ExecutionResult:
        """Execute with seccomp filtering"""
        
        # Generate seccomp profile
        profile = self._generate_seccomp_profile()
        profile_path = tempfile.mktemp(suffix='.json')
        
        with open(profile_path, 'w') as f:
            json.dump(profile, f)
        
        start_time = time.time()
        
        try:
            # Use Docker with seccomp profile
            result = subprocess.run([
                'docker', 'run', '--rm',
                '--security-opt', f'seccomp={profile_path}',
                'python:3.11-alpine',
                'sh', '-c', command
            ], capture_output=True, text=True,
                timeout=self.policy.max_execution_time)
            
            execution_time = time.time() - start_time
            
            # Check for syscall violations
            violations = []
            if 'operation not permitted' in result.stderr.lower():
                violations.append("Blocked syscall attempted")
                self._log_security_event('SYSCALL_BLOCKED', {'command': command})
            
            return ExecutionResult(
                success=(result.returncode == 0),
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
                execution_time=execution_time,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=[]
            )
            
        finally:
            if os.path.exists(profile_path):
                os.remove(profile_path)


class ProcessSandbox(SandboxExecutor):
    """
    Lightweight subprocess sandbox with resource limits.
    Default fallback when Docker/unshare are unavailable.
    """

    def __init__(self, policy: SecurityPolicy):
        super().__init__(policy, IsolationMethod.NAMESPACE)

    def execute(self, command: str, working_dir: str = None) -> ExecutionResult:
        cwd = working_dir or tempfile.mkdtemp(prefix="prom_sandbox_")
        start_time = time.time()
        violations: List[str] = []

        def _limits():
            mem = self.policy.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (self.policy.max_execution_time, self.policy.max_execution_time + 1),
            )
            resource.setrlimit(
                resource.RLIMIT_NPROC,
                (self.policy.max_processes, self.policy.max_processes),
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.policy.max_execution_time,
                cwd=cwd,
                preexec_fn=_limits,
            )
            elapsed = time.time() - start_time
            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
                execution_time=elapsed,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=[],
            )
        except subprocess.TimeoutExpired:
            violations.append(f"Execution timeout: {self.policy.max_execution_time}s exceeded")
            return ExecutionResult(
                success=False,
                output="",
                error=f"Timeout after {self.policy.max_execution_time}s",
                exit_code=-1,
                execution_time=float(self.policy.max_execution_time),
                memory_used_mb=0,
                policy_violations=violations,
                security_events=[],
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                output="",
                error=str(exc),
                exit_code=-1,
                execution_time=time.time() - start_time,
                memory_used_mb=0,
                policy_violations=violations,
                security_events=[],
            )


class CapabilityBasedSecurity:
    """
    Capability-based security model for tool access
    Each tool gets a capability token with specific permissions
    """
    
    def __init__(self):
        self.capabilities = {}
        self.revoked_capabilities = set()
        
    def grant_capability(self, tool_id: str, permissions: List[str],
                        expires_at: float = None) -> str:
        """
        Grant capability token to tool
        
        Args:
            tool_id: Unique identifier for tool
            permissions: List of allowed operations
            expires_at: Unix timestamp for expiration
        
        Returns:
            Capability token (JWT-like)
        """
        capability = {
            'tool_id': tool_id,
            'permissions': permissions,
            'granted_at': time.time(),
            'expires_at': expires_at,
            'uses_remaining': None  # Can add use limits
        }
        
        # Generate secure token
        token_data = json.dumps(capability, sort_keys=True)
        token = hashlib.sha256(token_data.encode()).hexdigest()
        
        self.capabilities[token] = capability
        
        logger.info(f"Granted capability {token[:16]}... to {tool_id}")
        
        return token
    
    def verify_capability(self, token: str, required_permission: str) -> bool:
        """
        Verify capability token has required permission
        
        Args:
            token: Capability token
            required_permission: Permission needed for operation
        
        Returns:
            True if capability is valid and has permission
        """
        # Check if token exists
        if token not in self.capabilities:
            logger.warning(f"Unknown capability token: {token[:16]}...")
            return False
        
        # Check if revoked
        if token in self.revoked_capabilities:
            logger.warning(f"Revoked capability token: {token[:16]}...")
            return False
        
        capability = self.capabilities[token]
        
        # Check expiration
        if capability['expires_at'] and time.time() > capability['expires_at']:
            logger.warning(f"Expired capability token: {token[:16]}...")
            return False
        
        # Check permission
        if required_permission not in capability['permissions']:
            logger.warning(
                f"Capability {token[:16]}... lacks permission: {required_permission}"
            )
            return False
        
        return True
    
    def revoke_capability(self, token: str):
        """Revoke capability token"""
        self.revoked_capabilities.add(token)
        logger.info(f"Revoked capability: {token[:16]}...")


class SecureToolWrapper:
    """
    Wrapper for AI agent tools with security controls
    Enforces sandboxing and capability checks
    """
    
    def __init__(self, tool_id: str, isolation_method: IsolationMethod,
                 threat_level: ThreatLevel):
        self.tool_id = tool_id
        self.isolation_method = isolation_method
        self.threat_level = threat_level
        
        # Get appropriate security policy
        self.policy = SecurityPolicyFactory.get_policy(threat_level)
        
        # Create sandbox executor (fallback to ProcessSandbox)
        self.executor = self._build_executor(isolation_method, self.policy)

        # Capability manager
        self.capability_manager = CapabilityBasedSecurity()

        # Execution history for anomaly detection
        self.execution_history = []

    @staticmethod
    def _build_executor(method: IsolationMethod, policy: SecurityPolicy):
        builders = {
            IsolationMethod.DOCKER: DockerSandbox,
            IsolationMethod.NAMESPACE: NamespaceSandbox,
            IsolationMethod.SECCOMP: SeccompSandbox,
        }
        cls = builders.get(method, ProcessSandbox)
        try:
            executor = cls(policy)
            if method in (IsolationMethod.DOCKER, IsolationMethod.NAMESPACE):
                probe = executor.execute("echo prometheous_sandbox_probe")
                if not probe.success:
                    err = (probe.error or "").lower()
                    if "docker" in err or "unshare" in err or "permission" in err:
                        logger.warning("%s sandbox probe failed, using ProcessSandbox", method.value)
                        return ProcessSandbox(policy)
            return executor
        except Exception as exc:
            logger.warning("sandbox %s unavailable (%s), using ProcessSandbox", method.value, exc)
            return ProcessSandbox(policy)
        
    def execute_tool(self, command: str, capability_token: str,
                    required_permission: str = "execute") -> ExecutionResult:
        """
        Execute tool with security controls
        
        Args:
            command: Command to execute
            capability_token: Capability token for authorization
            required_permission: Permission required for this operation
        
        Returns:
            ExecutionResult with output and security info
        """
        # Verify capability
        if not self.capability_manager.verify_capability(
            capability_token, required_permission
        ):
            return ExecutionResult(
                success=False,
                output="",
                error="Capability verification failed",
                exit_code=-1,
                execution_time=0,
                memory_used_mb=0,
                policy_violations=["Insufficient capabilities"],
                security_events=[{
                    'type': 'CAPABILITY_DENIED',
                    'tool_id': self.tool_id,
                    'permission': required_permission
                }]
            )
        
        # Check for anomalies (log; PrometheousSandboxGate can block upstream)
        if self._detect_anomaly(command):
            logger.warning("Anomalous command detected: %s...", command[:100])

        # Execute in sandbox
        result = self.executor.execute(command)
        
        # Record execution
        self.execution_history.append({
            'timestamp': time.time(),
            'command': command,
            'success': result.success,
            'execution_time': result.execution_time,
            'violations': result.policy_violations
        })
        
        return result
    
    def _detect_anomaly(self, command: str) -> bool:
        """
        Detect anomalous commands
        Simple heuristics - could use ML model
        """
        # Check for suspicious patterns
        suspicious_patterns = [
            'rm -rf /',
            'dd if=/dev/zero',
            'fork bomb',
            ':(){ :|:& };:',
            'curl | sh',
            'wget | sh',
            '/dev/tcp',
            'nc -e',
            'bash -i',
            'eval(',
            'exec(',
        ]
        
        command_lower = command.lower()
        for pattern in suspicious_patterns:
            if pattern in command_lower:
                return True
        
        # Check command frequency (rate limiting)
        recent_commands = [
            h for h in self.execution_history
            if time.time() - h['timestamp'] < 60
        ]
        
        if len(recent_commands) > 100:  # More than 100 commands per minute
            logger.warning(f"High command rate: {len(recent_commands)}/min")
            return True
        
        return False
    
    def get_execution_stats(self) -> Dict:
        """Get execution statistics"""
        if not self.execution_history:
            return {}
        
        return {
            'total_executions': len(self.execution_history),
            'successful': sum(1 for h in self.execution_history if h['success']),
            'failed': sum(1 for h in self.execution_history if not h['success']),
            'avg_execution_time': sum(h['execution_time'] for h in self.execution_history) / len(self.execution_history),
            'total_violations': sum(len(h['violations']) for h in self.execution_history)
        }


def demonstrate_sandboxing():
    """Demonstrate the sandboxing system"""
    print("=" * 80)
    print("RUNTIME ISOLATION AND TOOL SANDBOXING DEMONSTRATION")
    print("=" * 80)
    
    # Create secure tool wrapper
    print("\n[1] Creating Secure Tool Wrapper...")
    print("-" * 80)
    
    tool = SecureToolWrapper(
        tool_id="bash_executor",
        isolation_method=IsolationMethod.DOCKER,
        threat_level=ThreatLevel.MEDIUM
    )
    
    print(f"✓ Tool created with {tool.threat_level.name} threat level")
    print(f"  Isolation: {tool.isolation_method.value}")
    print(f"  Max Memory: {tool.policy.max_memory_mb}MB")
    print(f"  Max CPU: {tool.policy.max_cpu_percent}%")
    print(f"  Max Time: {tool.policy.max_execution_time}s")
    print(f"  Network: {'Enabled' if tool.policy.network_enabled else 'Disabled'}")
    
    # Grant capabilities
    print("\n[2] Granting Capabilities...")
    print("-" * 80)
    
    token = tool.capability_manager.grant_capability(
        tool_id="bash_executor",
        permissions=["execute", "read", "write"],
        expires_at=time.time() + 3600  # 1 hour
    )
    
    print(f"✓ Capability token: {token[:32]}...")
    
    # Test safe command
    print("\n[3] Testing Safe Command...")
    print("-" * 80)
    
    result = tool.execute_tool(
        command="echo 'Hello from sandbox'",
        capability_token=token,
        required_permission="execute"
    )
    
    print(f"Success: {result.success}")
    print(f"Output: {result.output.strip()}")
    print(f"Time: {result.execution_time:.3f}s")
    print(f"Violations: {len(result.policy_violations)}")
    
    # Test restricted command
    print("\n[4] Testing Restricted Command...")
    print("-" * 80)
    
    result = tool.execute_tool(
        command="cat /etc/shadow",  # Should fail
        capability_token=token,
        required_permission="execute"
    )
    
    print(f"Success: {result.success}")
    print(f"Error: {result.error[:100] if result.error else 'None'}...")
    print(f"Violations: {result.policy_violations}")
    
    # Test timeout
    print("\n[5] Testing Timeout Protection...")
    print("-" * 80)
    
    result = tool.execute_tool(
        command="sleep 100",  # Exceeds timeout
        capability_token=token,
        required_permission="execute"
    )
    
    print(f"Success: {result.success}")
    print(f"Error: {result.error}")
    print(f"Violations: {result.policy_violations}")
    
    # Show statistics
    print("\n[6] Execution Statistics...")
    print("-" * 80)
    stats = tool.get_execution_stats()
    print(json.dumps(stats, indent=2))
    
    print("\n" + "=" * 80)
    print("Demonstration Complete!")
    print("=" * 80)


if __name__ == '__main__':
    demonstrate_sandboxing()
