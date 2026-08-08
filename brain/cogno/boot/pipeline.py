"""
cogno/boot/pipeline.py

Concrete fine-tuning pipeline for Prometheous agents.

Stages:
  1. Generate cogno-native cognitive examples (finetune.py)
  2. Optionally ingest public agent datasets (AgentTrove, FireAct)
  3. Convert session/task logs into trajectory examples
  4. Mix by configured ratios → SFT JSONL
  5. Build DPO pairs from revision + friction examples

Outputs (under data/learning/finetune/):
  sft_train.jsonl, sft_val.jsonl, sft_test.jsonl
  dpo_train.jsonl
  manifest.json
"""

from __future__ import annotations

import json
import os
import random
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterator

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from utils.config import cfg
from brain.cogno.boot.finetune import TrainingExample, generate_all, generate_stats

ROOT = cfg.ROOT
DEFAULT_CONFIG = ROOT / "config" / "finetune_config.yaml"


@dataclass
class ChatRecord:
    messages: list[dict[str, str]]
    metadata: dict[str, Any]

    def to_jsonl(self) -> str:
        return json.dumps({"messages": self.messages, "metadata": self.metadata}, ensure_ascii=False)


@dataclass
class DPORecord:
    prompt: list[dict[str, str]]
    chosen: str
    rejected: str
    metadata: dict[str, Any]

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def load_config(path: Path | str | None = None) -> dict:
    config_path = Path(path) if path else DEFAULT_CONFIG
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def cogno_to_chat(example: TrainingExample, system_prompt: str) -> ChatRecord:
    """Map cogno TrainingExample → ChatML messages."""
    obs = json.dumps(example.observation, ensure_ascii=False)
    peripheral = ", ".join(example.peripheral_hits) if example.peripheral_hits else "none"

    assistant = (
        f"<thinking_v1>{example.thought_v1}</thinking_v1>\n"
        f"<observation>{obs}</observation>\n"
        f"<peripheral>{peripheral}</peripheral>\n"
        f"<revision_count>{example.revision_count}</revision_count>\n"
        f"<thinking_final>{example.thought_final}</thinking_final>\n"
        f"<choice>{example.choice}</choice>\n"
        f"<action>{example.action}</action>\n"
        f"<outcome>{example.outcome}</outcome>"
    )

    return ChatRecord(
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": example.input},
            {"role": "assistant", "content": assistant},
        ],
        metadata={
            "source": "cogno_native",
            "category": example.category,
            "friction_added": example.friction_added,
            "revision_count": example.revision_count,
            "id": _stable_id(example.category, example.input, example.choice),
        },
    )


def cogno_to_dpo(example: TrainingExample, system_prompt: str) -> DPORecord | None:
    """Build preference pair when the agent revised or hit friction."""
    if example.revision_count == 0 and example.friction_added == 0:
        return None

    prompt = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": example.input},
    ]
    chosen = (
        f"<thinking>{example.thought_final}</thinking>\n"
        f"<choice>{example.choice}</choice>\n"
        f"<action>{example.action}</action>"
    )
    rejected = (
        f"<thinking>{example.thought_v1}</thinking>\n"
        f"<choice>PROCEED</choice>\n"
        f"<action>continue without revision</action>"
    )
    return DPORecord(
        prompt=prompt,
        chosen=chosen,
        rejected=rejected,
        metadata={
            "source": "failure_recovery",
            "category": example.category,
            "id": _stable_id("dpo", example.category, example.input),
        },
    )


def _normalize_hf_messages(row: dict, text_field: str) -> list[dict[str, str]] | None:
    raw = row.get(text_field) or row.get("messages") or row.get("conversations")
    if not raw:
        return None

    messages: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or item.get("from") or ""
        content = item.get("content") or item.get("value") or ""
        role_map = {"human": "user", "gpt": "assistant", "bot": "assistant"}
        role = role_map.get(role, role)
        if role in ("system", "user", "assistant") and content:
            messages.append({"role": role, "content": str(content)})
    return messages or None


def load_public_dataset(name: str, spec: dict) -> list[ChatRecord]:
    """Load HuggingFace dataset slice. Returns [] if `datasets` is unavailable."""
    try:
        from datasets import load_dataset
    except ImportError:
        return []

    hf_id = spec.get("hf_id")
    if not hf_id:
        return []

    split = spec.get("split", "train")
    max_samples = int(spec.get("max_samples", 1000))
    text_field = spec.get("text_field", "messages")

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")

    try:
        ds = load_dataset(hf_id, split=split, streaming=True, token=token)
    except Exception:
        return []

    records: list[ChatRecord] = []
    for i, row in enumerate(ds):
        if i >= max_samples:
            break
        messages = _normalize_hf_messages(row, text_field)
        if not messages:
            continue
        records.append(
            ChatRecord(
                messages=messages,
                metadata={"source": name, "hf_id": hf_id, "id": _stable_id(name, str(i))},
            )
        )
    return records


def session_logs_to_chat(config: dict, system_prompt: str) -> list[ChatRecord]:
    """Turn task_memory + agent_memory sessions into lightweight SFT rows."""
    records: list[ChatRecord] = []
    sources = config.get("session_sources", [])

    for pattern in sources:
        for path in sorted(ROOT.glob(pattern)):
            if path.suffix == ".jsonl" and path.name == "trajectories.jsonl":
                records.extend(_trajectory_rows(path, system_prompt))
            elif path.suffix == ".json" and path.name == "task_memory.json":
                records.extend(_task_memory_rows(path, system_prompt))
            elif path.is_dir():
                records.extend(_agent_memory_dir(path, system_prompt))
    return records


def _trajectory_rows(path: Path, system_prompt: str) -> list[ChatRecord]:
    records: list[ChatRecord] = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except Exception:
        return []

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not entry.get("success"):
            continue

        payload = entry.get("payload") or {}
        user = payload.get("user_msg") or payload.get("goal") or payload.get("query")
        if not user:
            user = f"Execute {entry.get('intent', 'task')} via {entry.get('agent', 'agent')}"

        result = entry.get("result") or {}
        assistant = (
            f"<thinking>Dispatch to {entry.get('agent')} succeeded.</thinking>\n"
            f"<choice>COMPLETE</choice>\n"
            f"<action>{entry.get('intent')}:{entry.get('agent')}</action>\n"
            f"<outcome>{result.get('status', 'done')} in {entry.get('duration', 'n/a')}s</outcome>"
        )
        records.append(
            ChatRecord(
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": str(user)},
                    {"role": "assistant", "content": assistant},
                ],
                metadata={
                    "source": "session_logs",
                    "trajectory": True,
                    "task_id": entry.get("task_id"),
                    "agent": entry.get("agent"),
                    "id": _stable_id("traj", str(entry.get("task_id")), str(user)[:80]),
                },
            )
        )
    return records


def _task_memory_rows(path: Path, system_prompt: str) -> list[ChatRecord]:
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return []

    records: list[ChatRecord] = []
    for entry in entries:
        if entry.get("result") != "success":
            continue
        task = entry.get("task", "unknown")
        metrics = entry.get("metrics") or {}
        user = f"Execute task: {task}"
        if metrics.get("intent"):
            user += f" (intent={metrics['intent']})"

        assistant = (
            f"<thinking>Task {task} completed successfully.</thinking>\n"
            f"<choice>COMPLETE</choice>\n"
            f"<action>dispatch:{task}</action>\n"
            f"<outcome>success in {metrics.get('duration', 'n/a')}s</outcome>"
        )
        records.append(
            ChatRecord(
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ],
                metadata={"source": "session_logs", "task": task, "id": _stable_id(task, str(entry.get("time")))},
            )
        )
    return records


def _agent_memory_dir(path: Path, system_prompt: str) -> list[ChatRecord]:
    records: list[ChatRecord] = []
    for task_file in sorted(path.glob("task_*.json")):
        try:
            with open(task_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if data.get("status") != "ok":
            continue
        goal = data.get("goal", "")
        assistant = (
            f"<thinking>Recorded deterministic outcome.</thinking>\n"
            f"<choice>COMPLETE</choice>\n"
            f"<action>save_session</action>\n"
            f"<outcome>{data.get('note', 'ok')}</outcome>"
        )
        records.append(
            ChatRecord(
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": goal},
                    {"role": "assistant", "content": assistant},
                ],
                metadata={"source": "session_logs", "session_dir": path.name, "id": _stable_id(path.name, goal)},
            )
        )
    return records


def _sample_pool(pool: list, count: int, rng: random.Random) -> list:
    if not pool or count <= 0:
        return []
    if count >= len(pool):
        return list(pool)
    return rng.sample(pool, count)


def _split_records(
    records: list[ChatRecord], train_n: int, val_n: int, test_n: int, rng: random.Random
) -> tuple[list[ChatRecord], list[ChatRecord], list[ChatRecord]]:
    shuffled = list(records)
    rng.shuffle(shuffled)
    total = train_n + val_n + test_n
    if len(shuffled) > total:
        shuffled = shuffled[:total]

    n = len(shuffled)
    if n == 0:
        return [], [], []

    # Proportional split when pool is smaller than requested totals
    if n < total:
        val_take = max(1, round(n * val_n / total)) if val_n else 0
        test_take = max(1, round(n * test_n / total)) if test_n else 0
        if val_take + test_take >= n:
            val_take = 1 if n > 2 and val_n else 0
            test_take = 1 if n > 1 and test_n else 0
        train_take = n - val_take - test_take
        train = shuffled[:train_take]
        val = shuffled[train_take : train_take + val_take]
        test = shuffled[train_take + val_take :]
        return train, val, test

    train = shuffled[:train_n]
    val = shuffled[train_n : train_n + val_n]
    test = shuffled[train_n + val_n : train_n + val_n + test_n]
    return train, val, test


def build_mixed_dataset(config: dict | None = None, seed: int = 42) -> dict[str, Any]:
    """Run full pipeline and write JSONL artifacts."""
    config = config or load_config()
    rng = random.Random(seed)
    system_prompt = config.get("system_prompt", "")
    mix = config.get("mix", {})
    splits = config.get("splits", {"train": 8000, "val": 500, "test": 500})

    train_total = int(splits.get("train", 8000))
    val_total = int(splits.get("val", 500))
    test_total = int(splits.get("test", 500))
    grand_total = train_total + val_total + test_total

    # ── collect source pools ──
    cogno_examples = generate_all()
    cogno_chats = [cogno_to_chat(e, system_prompt) for e in cogno_examples]
    cogno_dpo = [r for e in cogno_examples if (r := cogno_to_dpo(e, system_prompt))]

    public_pools: dict[str, list[ChatRecord]] = {}
    for name, spec in (config.get("public_datasets") or {}).items():
        public_pools[name] = load_public_dataset(name, spec)

    session_pool = session_logs_to_chat(config, system_prompt)

    # ── allocate counts from mix ──
    allocations = {k: int(round(grand_total * float(v))) for k, v in mix.items()}
    # fix rounding drift
    drift = grand_total - sum(allocations.values())
    if drift and allocations:
        allocations["cogno_native"] = allocations.get("cogno_native", 0) + drift

    mixed: list[ChatRecord] = []
    mixed.extend(_expand_cogno(cogno_chats, allocations.get("cogno_native", 0), rng))
    mixed.extend(_expand_pool(public_pools.get("agenttrove", []), allocations.get("public_agenttrove", 0), rng, "public_agenttrove"))
    mixed.extend(_expand_pool(public_pools.get("fireact", []), allocations.get("public_fireact", 0), rng, "public_fireact"))
    mixed.extend(_expand_pool(session_pool, allocations.get("session_logs", 0), rng, "session_logs"))

    rng.shuffle(mixed)
    train, val, test = _split_records(mixed, train_total, val_total, test_total, rng)

    # DPO: friction/revision pairs + optional oversample
    dpo_target = max(int(train_total * float(mix.get("failure_recovery", 0.05))), len(cogno_dpo))
    dpo_records = _expand_dpo(cogno_dpo, dpo_target, rng)

    # ── write outputs ──
    out_dir = ROOT / config.get("output_dir", "data/learning/finetune")
    dry_run = bool(config.get("dry_run"))
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(out_dir / "sft_train.jsonl", train)
        _write_jsonl(out_dir / "sft_val.jsonl", val)
        _write_jsonl(out_dir / "sft_test.jsonl", test)
        _write_jsonl(out_dir / "dpo_train.jsonl", dpo_records)

    manifest = {
        "version": config.get("version", "1.0"),
        "seed": seed,
        "splits": {"train": len(train), "val": len(val), "test": len(test), "dpo": len(dpo_records)},
        "mix_requested": mix,
        "allocations": allocations,
        "source_counts": {
            "cogno_native": len(cogno_chats),
            "public_agenttrove": len(public_pools.get("agenttrove", [])),
            "public_fireact": len(public_pools.get("fireact", [])),
            "session_logs": len(session_pool),
            "cogno_dpo": len(cogno_dpo),
        },
        "cogno_stats": generate_stats(cogno_examples),
        "outputs": {
            "sft_train": str(out_dir / "sft_train.jsonl"),
            "sft_val": str(out_dir / "sft_val.jsonl"),
            "sft_test": str(out_dir / "sft_test.jsonl"),
            "dpo_train": str(out_dir / "dpo_train.jsonl"),
        },
        "public_data_available": {
            "agenttrove": len(public_pools.get("agenttrove", [])) > 0,
            "fireact": len(public_pools.get("fireact", [])) > 0,
        },
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    if config.get("write_stream_manifest"):
        stream_sources = {
            "mode": "hf_streaming",
            "note": "Pull rows at train-time via HTTP stream — no full corpus download",
            "sources": [
                {
                    "name": name,
                    "hf_id": spec.get("hf_id"),
                    "split": spec.get("split", "train"),
                    "max_samples": spec.get("max_samples", 1000),
                    "text_field": spec.get("text_field", "messages"),
                    "mix_weight": mix.get(f"public_{name}", mix.get(name, 0)),
                }
                for name, spec in (config.get("public_datasets") or {}).items()
                if spec.get("hf_id")
            ],
            "local_sources": {
                "cogno": "brain/cogno/boot/finetune.py",
                "trajectories": str(cfg.DATA_DIR / "learning" / "trajectories.jsonl"),
            },
        }
        with open(out_dir / "stream_sources.json", "w", encoding="utf-8") as f:
            json.dump(stream_sources, f, indent=2)
        manifest["stream_sources"] = str(out_dir / "stream_sources.json")

    return manifest


def _expand_cogno(pool: list[ChatRecord], count: int, rng: random.Random) -> list[ChatRecord]:
    if count <= 0 or not pool:
        return []
    out: list[ChatRecord] = []
    while len(out) < count:
        out.extend(pool)
    rng.shuffle(out)
    return out[:count]


def _expand_pool(
    pool: list[ChatRecord], count: int, rng: random.Random, source_label: str
) -> list[ChatRecord]:
    if count <= 0:
        return []
    if not pool:
        return []
    out: list[ChatRecord] = []
    while len(out) < count:
        out.extend(pool)
    rng.shuffle(out)
    return out[:count]


def _expand_dpo(pool: list[DPORecord], count: int, rng: random.Random) -> list[DPORecord]:
    if count <= 0 or not pool:
        return []
    out: list[DPORecord] = []
    while len(out) < count:
        out.extend(pool)
    rng.shuffle(out)
    return out[:count]


def _write_jsonl(path: Path, records: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(record.to_jsonl() + "\n")


if __name__ == "__main__":
    manifest = build_mixed_dataset()
    print(json.dumps(manifest, indent=2))