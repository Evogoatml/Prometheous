"""
Real port scanner — async TCP + nmap/naabu/masscan fallback.

Public surface:
    async scan_ports(host, ports, *, timeout=1.5, grab_banner=True,
                     engine="auto") -> list[dict]
    sync_scan(host, ports, **kwargs) -> list[dict]   (used by tool controller)

Each result dict has: {"port": int, "status": "open"|"closed"|"filtered",
"service": "ssh"|"http"|...?, "banner": str|None, "latency_ms": int|None}

`engine` is one of:
    "auto"   — pick best available; pure-async for small ranges,
               naabu/masscan/nmap for large ranges
    "async"  — pure asyncio TCP connect + optional banner grab
    "nmap"   — nmap -sT -Pn -p <ports> <host>   (most informative)
    "naabu"  — naabu -host <host> -p <ports> -silent -json
    "masscan"— masscan -p <ports> <host> --rate 1000
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Common ports used when caller does not specify — kept consistent with the
# default list the scanner agent already uses.
DEFAULT_PORTS = [22, 80, 443, 8080, 3389, 5900, 3306, 5432, 6379, 27017, 8443]

# Best-guess service name per port. Used as a fallback when banner grab fails.
WELL_KNOWN_SERVICES = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    80: "http", 110: "pop3", 111: "rpcbind", 135: "msrpc", 139: "netbios",
    143: "imap", 161: "snmp", 389: "ldap", 443: "https", 445: "smb",
    465: "smtps", 514: "syslog", 587: "submission", 631: "ipp",
    873: "rsync", 993: "imaps", 995: "pop3s", 1080: "socks", 1194: "openvpn",
    1433: "mssql", 1521: "oracle", 1723: "pptp", 1883: "mqtt", 2049: "nfs",
    2375: "docker", 2376: "docker-tls", 3000: "http-alt", 3306: "mysql",
    3389: "rdp", 5000: "upnp", 5432: "postgres", 5601: "kibana", 5900: "vnc",
    5984: "couchdb", 6379: "redis", 6443: "kube-api", 7001: "weblogic",
    8000: "http-alt", 8008: "http-alt", 8080: "http-alt", 8081: "http-alt",
    8443: "https-alt", 8888: "http-alt", 9000: "fpm", 9090: "prometheus",
    9092: "kafka", 9200: "elasticsearch", 9418: "git", 11211: "memcached",
    15672: "rabbitmq-mgmt", 27017: "mongodb", 27018: "mongodb", 27019: "mongodb",
}

# Probes for protocols that don't speak first — send something and read.
_PROBES: Dict[int, bytes] = {
    80: b"HEAD / HTTP/1.0\r\nUser-Agent: prometheous\r\n\r\n",
    8080: b"HEAD / HTTP/1.0\r\nUser-Agent: prometheous\r\n\r\n",
    8000: b"HEAD / HTTP/1.0\r\nUser-Agent: prometheous\r\n\r\n",
    443: b"",  # TLS — leave to nmap for proper detection
    3306: b"",  # MySQL server greeting
    5432: b"",  # Postgres error
    6379: b"PING\r\n",
    9200: b"GET / HTTP/1.0\r\n\r\n",
    11211: b"version\r\n",
}


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


def _pick_engine(ports: List[int], engine: str) -> str:
    """Choose a scanner engine. Public callers may override via `engine`."""
    if engine != "auto":
        return engine
    if len(ports) > 500 and _have("masscan"):
        return "masscan"
    if len(ports) > 200 and _have("naabu"):
        return "naabu"
    if _have("nmap") and len(ports) <= 50:
        return "nmap"
    return "async"


async def _probe_one(host: str, port: int, timeout: float, grab_banner: bool) -> Dict[str, Any]:
    """Connect to host:port. On success, optionally grab a banner."""
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
        # Refused -> closed. Timeout -> filtered. Other -> filtered.
        if isinstance(e, ConnectionRefusedError):
            return {"port": port, "status": "closed", "service": None, "banner": None, "latency_ms": None}
        return {"port": port, "status": "filtered", "service": None, "banner": None, "latency_ms": None}

    latency_ms = int((time.monotonic() - start) * 1000)
    banner: Optional[str] = None
    service: Optional[str] = WELL_KNOWN_SERVICES.get(port)

    if grab_banner:
        try:
            probe = _PROBES.get(port, b"")
            if probe:
                writer.write(probe)
                await writer.drain()
            data = await asyncio.wait_for(reader.read(128), timeout=0.6)
            if data:
                banner = data[:120].decode("utf-8", errors="replace").strip()
                # Cheap service guess from banner
                bl = banner.lower()
                if "ssh-" in bl:
                    service = "ssh"
                elif bl.startswith("http/"):
                    service = "https" if port == 443 else "http"
                elif "redis" in bl or banner.startswith("+PONG"):
                    service = "redis"
                elif "mysql" in bl:
                    service = "mysql"
                elif "postgres" in bl:
                    service = "postgres"
                elif "rabbitmq" in bl:
                    service = "rabbitmq"
        except (asyncio.TimeoutError, ConnectionResetError, OSError):
            pass

    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

    return {"port": port, "status": "open", "service": service, "banner": banner, "latency_ms": latency_ms}


async def _async_scan(host: str, ports: List[int], timeout: float, grab_banner: bool, concurrency: int) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)

    async def bounded(p: int) -> Dict[str, Any]:
        async with sem:
            return await _probe_one(host, p, timeout, grab_banner)

    results = await asyncio.gather(*[bounded(p) for p in ports])
    return sorted(results, key=lambda r: r["port"])


def _parse_nmap(xml: str) -> List[Dict[str, Any]]:
    """Very small nmap XML parser — only the bits we need."""
    import re
    out: List[Dict[str, Any]] = []
    # nmap's <port> can have attributes in any order: portid/proto,
    # protocol/portid, etc. Match by <port ...>...</port> then read fields.
    for m in re.finditer(r'<port\b([^>]*)>(.*?)</port>', xml, re.S):
        attrs, block = m.group(1), m.group(2)
        port_m = re.search(r'portid="(\d+)"', attrs)
        if not port_m:
            continue
        if 'protocol="tcp"' not in attrs and 'protocol="tcp"' not in block:
            # default to tcp if only one protocol scanned
            if re.search(r'<scaninfo[^>]*protocol="tcp"', xml[:2000]):
                pass  # ok, it's tcp
            else:
                continue
        port = int(port_m.group(1))
        state_m = re.search(r'<state\s+state="([^"]+)"', block)
        name_m = re.search(r'<service\s+name="([^"]+)"', block)
        product_m = re.search(r'product="([^"]+)"', block)
        version_m = re.search(r'version="([^"]+)"', block)
        state = state_m.group(1) if state_m else "unknown"
        status = "open" if state == "open" else ("filtered" if state == "filtered" else "closed")
        service = name_m.group(1) if name_m else None
        banner_parts = [p for p in [product_m.group(1) if product_m else None,
                                    version_m.group(1) if version_m else None] if p]
        banner = " ".join(banner_parts) or None
        out.append({"port": port, "status": status, "service": service, "banner": banner, "latency_ms": None})
    return sorted(out, key=lambda r: r["port"])


def _run_nmap(host: str, ports: List[int]) -> List[Dict[str, Any]]:
    cmd = ["nmap", "-sT", "-Pn", "-n", "--max-retries", "1", "--host-timeout", "20s",
           "-p", ",".join(str(p) for p in ports), "-oX", "-", host]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 and not r.stdout:
            raise RuntimeError(f"nmap failed: {r.stderr[:200]}")
        return _parse_nmap(r.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("nmap unavailable / timed out, falling back to async: %s", e)
        return asyncio.run(_async_scan(host, ports, 1.5, True, 200))


def _run_naabu(host: str, ports: List[int]) -> List[Dict[str, Any]]:
    cmd = ["naabu", "-host", host, "-p", ",".join(str(p) for p in ports), "-silent", "-json", "-nmap-cli", "false"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out: List[Dict[str, Any]] = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            port = rec.get("port")
            if port is None:
                continue
            out.append({"port": int(port), "status": "open", "service": WELL_KNOWN_SERVICES.get(int(port)),
                        "banner": None, "latency_ms": None})
        if not out:
            return asyncio.run(_async_scan(host, ports, 1.5, True, 200))
        return sorted(out, key=lambda r: r["port"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("naabu unavailable / timed out, falling back to async: %s", e)
        return asyncio.run(_async_scan(host, ports, 1.5, True, 200))


def _run_masscan(host: str, ports: List[int]) -> List[Dict[str, Any]]:
    cmd = ["masscan", "-p", ",".join(str(p) for p in ports), host, "--rate", "1000", "-oJ", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out: List[Dict[str, Any]] = []
        for line in r.stdout.splitlines():
            line = line.strip().rstrip(",")
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            port = rec.get("port")
            if port is None:
                continue
            out.append({"port": int(port), "status": "open", "service": WELL_KNOWN_SERVICES.get(int(port)),
                        "banner": None, "latency_ms": None})
        if not out:
            return asyncio.run(_async_scan(host, ports, 1.5, True, 200))
        return sorted(out, key=lambda r: r["port"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("masscan unavailable / timed out, falling back to async: %s", e)
        return asyncio.run(_async_scan(host, ports, 1.5, True, 200))


async def scan_ports(host: str,
                     ports: Optional[Iterable[int]] = None,
                     *,
                     timeout: float = 1.5,
                     grab_banner: bool = True,
                     engine: str = "auto",
                     concurrency: int = 200) -> List[Dict[str, Any]]:
    """
    Scan `host` on `ports`. Returns a list of result dicts.
    `engine`: "auto" | "async" | "nmap" | "naabu" | "masscan"
    """
    if ports is None:
        ports = DEFAULT_PORTS
    port_list = sorted({int(p) for p in ports if 0 < int(p) < 65536})
    if not port_list:
        return []

    # resolve hostname once so we don't redo it per port
    try:
        await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return [{"error": f"dns resolution failed for {host}: {e}"}]

    chosen = _pick_engine(port_list, engine)
    logger.info("port_scan host=%s ports=%d engine=%s", host, len(port_list), chosen)

    if chosen == "nmap":
        return await asyncio.get_running_loop().run_in_executor(None, _run_nmap, host, port_list)
    if chosen == "naabu":
        return await asyncio.get_running_loop().run_in_executor(None, _run_naabu, host, port_list)
    if chosen == "masscan":
        return await asyncio.get_running_loop().run_in_executor(None, _run_masscan, host, port_list)
    return await _async_scan(host, port_list, timeout, grab_banner, concurrency)


def sync_scan(host: str, ports: Optional[Iterable[int]] = None, **kwargs) -> List[Dict[str, Any]]:
    """Synchronous wrapper used by the tool controller (which is sync)."""
    return asyncio.run(scan_ports(host, ports, **kwargs))


# Backwards-compat: original return shape was {"output": str}. The tool
# controller's caller in agents/scanner.py does .get("result") and then
# stringifies — both new and old shapes work since list[dict] is JSON-ish.
def to_controller_output(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    open_ports = [r["port"] for r in results if r.get("status") == "open"]
    return {
        "output": json.dumps({
            "host_scanned": True,
            "open_ports": open_ports,
            "open_count": len(open_ports),
            "results": results,
        }),
        "open_ports": open_ports,
        "results": results,
    }
