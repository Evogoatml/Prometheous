#!/usr/bin/env python3
"""
ELITE KNOWLEDGE BASE - What the top 0.01% know
"""

ELITE_KNOWLEDGE = """

=== MODE 1: HIDDEN KNOWLEDGE HUNTER ===

1. TIMING-BASED DATA EXFILTRATION
- DNS timing patterns, HTTP response time variations
- TCP window sizes encode information
- Statistical patterns in legitimate traffic - no payload needed
- Exfiltrate from air-gapped networks using packet timing

2. TRUST INHERITANCE VULNERABILITY  
- JWTs, OAuth tokens, session cookies trusted blindly
- Find where validation trusts token EXISTENCE more than CONTENTS
- Low-privilege token to high-privilege endpoint without scope validation

3. DOM CLOBBERING AS FIRST-CLASS VECTOR
- Override JavaScript variables before security executes
- Weaponize prototype chains
- Turns "self-XSS" into account takeover

4. N+1 QUERY SIDE CHANNEL  
- Timing differences reveal database structure
- Single query: 50ms vs 100 users: 150ms = timing correlation
- Weaponize for blind SQL injection without error messages

5. DOCUMENTATION GAP EXPLOIT
- Documented API (v2) vs undocumented API (v1)
- Undocumented = forgotten = weaker validation
- Business logic assumed "nobody knows about v1" = secure

6. SUBDOMAIN TAKEOVER
- Abandoned MX records to expired mail services
- Stale NS records for decommissioned DNS
- Expired SSL allows subdomain claim on some cloud platforms

7. BUSINESS LOGIC RACE CONDITION
- Multi-step workflows are rarely atomic
- Parallelize requests across steps for state confusion
- Complete purchase twice, charged once
- Two concurrent approvals validate against stale state

8. MEMORY DEDUPLICATION ATTACKS
- KSM in Linux leaks info across containers
- Craft pages with specific patterns
- Measure deduplication timing
- Extract cryptographic keys from other containers

9. "COMPILED LOGIC" BLIND SPOT
- WebAssembly, compiled Python, bundled JS
- Contains logic removed from source for "performance"
- Debug endpoints, hardcoded keys, admin backdoors
- Exist only in production binaries

=== MODE 4: ELITE MASTERY ===

PHASE 1: FOUNDATION DESTRUCTION
- Wireshark every tool you run
- Understand every flag at TCP/UDP level
- Write your own scanners in Python/Go
- Study source code monthly: dirsearch, nuclei, sqlmap

PHASE 2: TARGET ACQUISITION
- Bug bounty programs  
- Intentionally vulnerable apps
- DVWA, Damn Vulnerable GraphQL App, Kubernetes Goat, CloudGoat

PHASE 3: SPECIALIZATION
- Web/API: JavaScript prototype pollution, GraphQL introspection
- Cloud: IAM policy analysis, metadata service exploitation
- Mobile: Frida instrumentation, SSL pinning bypass
- Network/Infra: AD bloodhound analysis, Kerberos attacks
- Hardware/IoT: Firmware extraction, JTAG/UART debugging

PHASE 4: AUTOMATION ARSENAL
- Custom wordlists from target's GitHub
- Recon pipelines: amass + httpx + nuclei + custom
- Build correlation: subdomain + technology + CVE = notification

PHASE 5: META-GAME
- Read Usenix/IEEE/ACM papers monthly
- Contribute to open source security tools
- Build $200+/month personal lab with realistic infrastructure

=== THE UNSPOKEN LAWS ===

LAW 1: CVS EFFECT
- Vulnerability reports = political instruments
- Trade findings strategically for access
- Don't report everything at once

LAW 2: SCOPE IS SUGGESTION
- Find gray zones, document carefully
- "Discovered during reconnaissance of in-scope assets"

LAW 3: REMEDIATION THEATER
- Package in compliance language: ISO 27001, SOC 2, PCI-DSS
- "SQL injection becomes A04:2021 - Insecure Design"

LAW 4: ATTRIBUTION GAME  
- Strategic timing over immediate disclosure
- 24-48 hours reveals additional vulnerabilities
- Within contract notification requirements

LAW 5: REPUTATION
- Security and discretion = CISOs call you directly

LAW 6: TOOL VENDOR COMPLEXITY
- Black-box tools create black-box understanding
- Open source + custom scripts > enterprise tools

LAW 7: CLIENT'S REAL FEAR
- Not hackers - they fear regulators, lawsuits, headlines
- Always include "Business Impact" section
- Vulnerability = priority when = liability

"""

# Elite attack techniques for scanning
ELITE_SCANS = {
    "timing": "measure HTTP response times, variations reveal DB structure",
    "dom": "inject via prototype chain manipulation",
    "race": "send parallel requests to workflow endpoints", 
    "graphql": "measure query times: 1 item vs 100 items = timing leak",
    "unlisted": "find undocumented API versions (v1 vs v2)",
    "subdomain": "check expired MX, NS, SSL records",
}

def get_elite_knowledge(topic: str = None) -> str:
    if topic:
        topic = topic.lower()
        if "timing" in topic:
            return ELITE_KNOWLEDGE.split("TIMING-BASED")[1].split("TRUST")[0]
        if "dom" in topic:
            return "DOM CLOBBERING: Override JS prototype before security runs. Turns self-XSS to account takeover."
        if "race" in topic:
            return "RACE CONDITION: Parallel requests to multi-step workflows cause state confusion."
        if "graphql" in topic:
            return "N+1 TIMING: 1 query=50ms, 100 queries=150ms reveals data structure."
        if "doc" in topic:
            return "DOC GAP: Undocumented API (v1) always weaker than documented (v2)."
        if "subdomain" in topic:
            return "SUB takeover: Expired MX, NS, SSL records for takeover."
    
    return ELITE_KNOWLEDGE

if __name__ == "__main__":
    print(get_elite_knowledge())