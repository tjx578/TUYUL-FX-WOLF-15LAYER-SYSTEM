"""
Journal GPT Bridge — Export journal data for TUYUL FX GPT analysis.

Provides:
  - _load_entries(): Load journal entries from storage
  - compute_metrics(): Calculate rejection rate, protection score, etc.
  - export_for_gpt(): Generate Markdown export for GPT analysis

GPT Role (LOCKED):
  ✅ Constitution Auditor, Journal Interpreter, Edge Miner, System Governor
  ❌ TIDAK mengubah threshold, TIDAK mengirim order, TIDAK override L12
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from utils.timezone_utils import now_utc


def _load_entries(
    date_range_days: int = 7,
    journal_types: Optional[List[str]] = None,
    base_dir: str = "storage/decision_archive",
) -> List[Dict[str, Any]]:
    """
    Load journal entries from storage.
    
    Args:
        date_range_days: Number of days to look back
        journal_types: Filter by journal types (e.g., ["decision", "execution"])
        base_dir: Base directory for journal storage
        
    Returns:
        List of journal entries (parsed JSON)
    """
    entries = []
    base_path = Path(base_dir)
    
    if not base_path.exists():
        logger.warning(f"Journal directory does not exist: {base_path}")
        return entries
    
    # Calculate date range
    end_date = now_utc()
    start_date = end_date - timedelta(days=date_range_days)
    
    # Iterate through date directories
    for date_dir in sorted(base_path.iterdir()):
        if not date_dir.is_dir():
            continue
        
        # Parse directory name (YYYY-MM-DD format)
        try:
            dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
            dir_date = dir_date.replace(tzinfo=end_date.tzinfo)
        except ValueError:
            continue
        
        # Skip if outside date range
        if dir_date < start_date or dir_date > end_date:
            continue
        
        # Load all JSON files in this directory
        for json_file in date_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                
                # Filter by journal type if specified
                if journal_types and entry.get("journal_type") not in journal_types:
                    continue
                
                entries.append(entry)
                
            except Exception as exc:
                logger.warning(f"Failed to load {json_file}: {exc}")
                continue
    
    logger.info(f"Loaded {len(entries)} journal entries from last {date_range_days} days")
    return entries


def compute_metrics(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute metrics from journal entries.
    
    Args:
        entries: List of journal entries
        
    Returns:
        Dictionary of computed metrics
    """
    decision_entries = [e for e in entries if e.get("journal_type") == "decision"]
    execution_entries = [e for e in entries if e.get("journal_type") == "execution"]
    reflection_entries = [e for e in entries if e.get("journal_type") == "reflection"]
    
    total_decisions = len(decision_entries)
    total_executions = len(execution_entries)
    
    # Count verdicts
    verdict_counts = Counter()
    for entry in decision_entries:
        verdict = entry.get("data", {}).get("verdict")
        if verdict:
            verdict_counts[verdict] += 1
    
    # Rejection rate
    rejected = verdict_counts.get("HOLD", 0) + verdict_counts.get("NO_TRADE", 0)
    rejection_rate = (rejected / total_decisions * 100) if total_decisions > 0 else 0.0
    
    # Failed gates analysis
    failed_gates_counter = Counter()
    for entry in decision_entries:
        failed_gates = entry.get("data", {}).get("failed_gates", [])
        for gate in failed_gates:
            failed_gates_counter[gate] += 1
    
    top_failed_gates = failed_gates_counter.most_common(5)
    
    # Protection assessment (from J4 reflections)
    protection_scores = []
    override_count = 0
    for entry in reflection_entries:
        data = entry.get("data", {})
        if data.get("did_system_protect") == "YES":
            protection_scores.append(1)
        elif data.get("did_system_protect") == "NO":
            protection_scores.append(0)
        
        if data.get("override_attempted"):
            override_count += 1
    
    protection_score = (
        sum(protection_scores) / len(protection_scores) * 100
        if protection_scores
        else None
    )
    
    # Average wolf score for EXECUTE verdicts
    execute_wolf_scores = []
    for entry in decision_entries:
        data = entry.get("data", {})
        verdict = data.get("verdict")
        if verdict in ["EXECUTE_BUY", "EXECUTE_SELL"]:
            wolf_score = data.get("wolf_30_score")
            if wolf_score is not None:
                execute_wolf_scores.append(wolf_score)
    
    avg_execute_wolf = (
        sum(execute_wolf_scores) / len(execute_wolf_scores)
        if execute_wolf_scores
        else None
    )
    
    return {
        "total_decisions": total_decisions,
        "total_executions": total_executions,
        "total_reflections": len(reflection_entries),
        "verdict_counts": dict(verdict_counts),
        "rejection_rate": round(rejection_rate, 1),
        "top_failed_gates": top_failed_gates,
        "protection_score": round(protection_score, 1) if protection_score else None,
        "override_count": override_count,
        "avg_execute_wolf_score": round(avg_execute_wolf, 1) if avg_execute_wolf else None,
    }


def export_for_gpt(
    date_range_days: int = 7,
    journal_types: Optional[List[str]] = None,
    output_dir: str = "storage/gpt_exports",
) -> Path:
    """
    Export journal data to Markdown file for GPT analysis.
    
    Args:
        date_range_days: Number of days to export
        journal_types: Filter by journal types (defaults to all)
        output_dir: Output directory for exports
        
    Returns:
        Path to generated Markdown file
    """
    # Load entries
    entries = _load_entries(date_range_days, journal_types)
    
    # Compute metrics
    metrics = compute_metrics(entries)
    
    # Prepare output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    now = now_utc()
    filename = f"JOURNAL_EXPORT_{now.strftime('%Y%m%d_%H%M%S')}.md"
    file_path = output_path / filename
    
    # Generate Markdown content
    with open(file_path, "w", encoding="utf-8") as f:
        # Header
        f.write("# TUYUL FX WOLF — Journal Export for GPT Analysis\n\n")
        f.write(f"**Generated:** {now.isoformat()}\n\n")
        f.write(f"**Period:** Last {date_range_days} days\n\n")
        f.write("---\n\n")
        
        # GPT Role reminder
        f.write("## GPT Role (LOCKED)\n\n")
        f.write("✅ **ALLOWED:**\n")
        f.write("- Constitution Auditor\n")
        f.write("- Journal Interpreter\n")
        f.write("- Edge Miner\n")
        f.write("- System Governor\n\n")
        f.write("❌ **FORBIDDEN:**\n")
        f.write("- Must NOT change thresholds\n")
        f.write("- Must NOT send orders\n")
        f.write("- Must NOT override L12\n\n")
        f.write("---\n\n")
        
        # Metrics summary
        f.write("## Metrics Summary\n\n")
        f.write(f"- **Total Decisions:** {metrics['total_decisions']}\n")
        f.write(f"- **Total Executions:** {metrics['total_executions']}\n")
        f.write(f"- **Total Reflections:** {metrics['total_reflections']}\n")
        f.write(f"- **Rejection Rate:** {metrics['rejection_rate']}%\n")
        
        if metrics['protection_score']:
            f.write(f"- **Protection Score:** {metrics['protection_score']}%\n")
        
        if metrics['avg_execute_wolf_score']:
            f.write(f"- **Avg Execute Wolf Score:** {metrics['avg_execute_wolf_score']}/30\n")
        
        f.write(f"- **Override Attempts:** {metrics['override_count']}\n\n")
        
        # Verdict distribution
        f.write("### Verdict Distribution\n\n")
        for verdict, count in sorted(metrics['verdict_counts'].items()):
            pct = (count / metrics['total_decisions'] * 100) if metrics['total_decisions'] > 0 else 0
            f.write(f"- **{verdict}:** {count} ({pct:.1f}%)\n")
        f.write("\n")
        
        # Top failed gates
        f.write("### Top Failed Gates\n\n")
        if metrics['top_failed_gates']:
            for gate, count in metrics['top_failed_gates']:
                f.write(f"- **{gate}:** {count} failures\n")
        else:
            f.write("*No gate failures recorded*\n")
        f.write("\n---\n\n")
        
        # Decision records (limit to 100 most recent)
        f.write("## Decision Records (Recent 100)\n\n")
        decision_entries = [e for e in entries if e.get("journal_type") == "decision"]
        decision_entries.sort(key=lambda x: x.get("recorded_at", ""), reverse=True)
        
        for entry in decision_entries[:100]:
            data = entry.get("data", {})
            f.write(f"### {data.get('setup_id', 'UNKNOWN')}\n\n")
            f.write("```json\n")
            f.write(json.dumps(data, indent=2))
            f.write("\n```\n\n")
    
    logger.info(f"GPT export generated: {file_path}")
    return file_path
