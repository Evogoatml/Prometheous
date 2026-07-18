"""
Service Registry
Clean separation layer between subsystems — each service has a well-defined
interface and is independently addressable.

Why:
  Proper separation lowers latency.  When subsystems talk through explicit
  service interfaces rather than direct imports, each path only pays for
  the services it actually uses.  Services can be swapped, mocked, or
  run remotely without touching callers.

Usage:
    from core.kernel.service_registry import registry

    # Register a service (usually done in the subsystem's init)
    registry.register("memory", my_memory_instance)

    # Look up a service (returns None if not registered)
    mem = registry.get("memory")

    # Or get with a factory (lazy init on first access)
    mem = registry.get_or_create("memory", factory=lambda: MemoryService())
"""

import logging
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """Thread-safe registry for subsystem services.

    Each service is registered under a string key and can be retrieved
    by any other subsystem without needing to know the implementation
    details or import path.
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._lock = threading.Lock()

    def register(self, name: str, service: Any):
        """Register a live service instance."""
        with self._lock:
            self._services[name] = service
            logger.debug("Service registered: %s", name)

    def register_factory(self, name: str, factory: Callable[[], Any]):
        """Register a factory for lazy service creation."""
        with self._lock:
            self._factories[name] = factory

    def get(self, name: str) -> Optional[Any]:
        """Get a service by name, or None if not registered."""
        with self._lock:
            svc = self._services.get(name)
            if svc is not None:
                return svc

            # Try factory
            factory = self._factories.get(name)
            if factory is not None:
                try:
                    svc = factory()
                    self._services[name] = svc
                    del self._factories[name]
                    logger.info("Service created via factory: %s", name)
                    return svc
                except Exception as e:
                    logger.warning("Factory failed for service %s: %s", name, e)
                    return None

            return None

    def get_or_create(self, name: str, factory: Callable[[], Any]) -> Optional[Any]:
        """Get service or create it via the provided factory on first access."""
        svc = self.get(name)
        if svc is not None:
            return svc

        with self._lock:
            # Double-check after acquiring lock
            if name in self._services:
                return self._services[name]
            try:
                svc = factory()
                self._services[name] = svc
                logger.info("Service created on demand: %s", name)
                return svc
            except Exception as e:
                logger.warning("On-demand creation failed for %s: %s", name, e)
                return None

    def has(self, name: str) -> bool:
        """Check if a service is registered (or has a factory)."""
        with self._lock:
            return name in self._services or name in self._factories

    def list_services(self) -> Dict[str, bool]:
        """Return dict of service names -> whether they're live (vs factory-pending)."""
        with self._lock:
            result = {}
            for name in set(list(self._services.keys()) + list(self._factories.keys())):
                result[name] = name in self._services
            return result

    def remove(self, name: str):
        """Remove a service."""
        with self._lock:
            self._services.pop(name, None)
            self._factories.pop(name, None)


# Module-level singleton
registry = ServiceRegistry()
