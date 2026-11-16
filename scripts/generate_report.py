from __future__ import annotations

import argparse
import html
import json
import re
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JOB_NAME = "comp-chem-world-local"
EXPECTED_TASKS = 186


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def task_description(task: Path) -> str:
    config = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    description = config.get("metadata", {}).get("description") or config.get("task", {}).get("description", "")
    return " ".join(description.split())


def is_hpc(task: Path) -> bool:
    suffixes = {".py", ".yaml", ".yml", ".toml", ".sh"}
    for path in task.rglob("*"):
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        if path.name == "Dockerfile" or path.suffix in suffixes:
            if "compchembench-connectivity" in path.read_text(encoding="utf-8", errors="ignore"):
                return True
    return False


def lfs_inputs(task: Path) -> list[str]:
    pointers = []
    for path in task.rglob("*"):
        if not path.is_file() or path.stat().st_size >= 200:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if text.startswith("version https://git-lfs.github.com/spec/v1"):
            pointers.append(path.relative_to(task).as_posix())
    return pointers


def verifier_reason(trial: Path) -> str:
    verifier = trial / "verifier"
    for name in ("verification.json", "case02-check.json"):
        path = verifier / name
        if path.is_file():
            try:
                data = load_json(path)
            except (json.JSONDecodeError, OSError):
                continue
            for key in ("reason", "message", "error", "review_note"):
                if data.get(key):
                    return str(data[key])
            if data.get("review", {}).get("reason"):
                return str(data["review"]["reason"])
            if data.get("errors"):
                return "; ".join(map(str, data["errors"]))
            if data.get("problems"):
                return "; ".join(map(str, data["problems"]))
            if data.get("failures"):
                return "; ".join(map(str, data["failures"]))
            if data.get("checks"):
                failed = [check for check in data["checks"] if not check.get("passed", True)]
                if failed:
                    return "; ".join(f"{check.get('name')}: {check.get('reason')}" for check in failed)
    for name in ("test-stdout.txt", "verifier.stdout", "verify.stdout.log"):
        path = verifier / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return text[-1500:]
    return "未找到更具体的 verifier 原因。"


def classify_failure(reward: float | None, exception: dict[str, Any], reason: str) -> tuple[str, str, str]:
    if exception:
        kind = exception.get("exception_type", "未知异常")
        message = exception.get("exception_message", "")
        combined = f"{message}\n{reason}"
        if kind == "AgentTimeoutError":
            return "Agent 超时", "模型在任务规定的时限内没有完成。这里反映执行时限与任务复杂度，不应直接等同于科学判断错误。", "高"
        if kind == "RewardFileNotFoundError":
            if "conditional wording" in reason:
                return "科学表述待复核", "模型给出的排序带有尚未验证的条件措辞，验证器要求进一步科学复核，因此没有出分；不能直接归类为 verifier 崩溃或模型科学错误。", "高"
            if "independent scientific review" in reason or "independent review" in reason.lower():
                return "独立复核未完成", "独立科学复核不可用或没有形成结论，因此 reward 未生成。这是审核流程未闭合，不是模型已经答错的证据。", "高"
            if "bound to different output bytes" in reason:
                return "审核绑定不一致", "已有科学审核绑定的是不同的输出字节，当前候选结果没有匹配的受信审核，因此未出分。", "高"
            return "Verifier 未出分", "验证流程没有生成 reward 文件。需要结合 verifier 日志判断是输出无效、验证脚本失败还是基础设施故障；当前不计作模型答错。", "高"
        if kind == "EnvironmentStartTimeoutError":
            return "环境启动超时", "任务环境未能在规定时间内启动，模型尚未进入有效解题阶段。", "高"
        if "exec format" in combined.lower() or "no match for platform" in combined.lower() or "aarch64" in combined.lower():
            return "架构不兼容", "构建记录包含 ARM64 依赖或平台约束，与当前 x86_64 主机不匹配。模型未开始实际解题。", "高"
        if "timed out" in combined.lower() or "readtimeout" in combined.lower() or "connection" in combined.lower():
            return "下载或网络", "依赖下载或网络连接超时，属于构建基础设施失败，不是模型科学能力结果。", "高"
        if "hash" in combined.lower() or "no matching distribution" in combined.lower():
            return "依赖或哈希", "Python 依赖的版本、平台或 SHA-256 校验未通过，任务镜像未能完成构建。", "高"
        return "环境构建", f"任务环境构建失败（{kind}）。{reason}", "中"
    lower = reason.lower()
    if "permissionerror" in lower or "permission denied" in lower:
        return "权限或验证环境", f"验证重放时发生文件权限错误：{reason}。这不能直接归因为模型不会。", "高"
    mappings = [
        ("threshold key domain", "输出结构", "阈值域的行集合存在缺失、额外或重复项。"),
        ("float' object is not subscriptable", "输出结构", "模型输出的字段层级或类型不符合验证器约定。"),
        ("cannot unpack non-iterable", "输出结构", "模型输出的记录结构不正确，验证器无法按预期解包。"),
        ("run metadata must hash", "输出结构", "运行元数据没有逐一、准确地记录公开输入的哈希。"),
        ("list indices must be integers", "输出结构", "模型输出的数据结构类型错误，列表被当成字典使用。"),
        ("evidence_ids", "输出结构", "证据引用 ID 没有指向任务中实际列出的来源。"),
        ("coefficients and gauge_constant", "输出结构", "缺少分析路径要求的系数与规范常数证书。"),
        ("field set differs", "输出结构", "科学报告的字段集合与任务契约不一致。"),
        ("condition coverage differs", "输出结构", "条件覆盖存在缺失、额外或重复记录。"),
        ("per-item samples missing", "输出结构", "指定条件下的逐样本结果不完整。"),
        ("expected finite numeric", "输出结构", "要求的数值字段缺失或不是有限数值。"),
        ("multiple of 62", "输出结构", "vectors CSV 的记录数量不符合输入结构要求。"),
    ]
    for needle, category, explanation in mappings:
        if needle.lower() in lower:
            return category, explanation + " 这属于模型没有遵守输出契约。", "高"
    scientific = [
        "quadrature mismatch", "sensitivity recomputation mismatch", "k_eq basis", "temperature_normalisation",
        "frequency_offset", "source pointer mismatch", "contradicts trusted facts", "syntaxerror",
    ]
    if any(needle in lower for needle in scientific):
        return "模型科学判断", f"模型完成并提交了结果，但科学计算或证据判断未通过验证：{reason}", "高"
    return "模型输出未通过", f"模型输出未满足本任务验证标准：{reason}。需要结合原始答案进一步细分。", "中"


def trial_record(result_path: Path) -> dict[str, Any]:
    data = load_json(result_path)
    trial = result_path.parent
    reward_data = data.get("verifier_result") or {}
    reward = reward_data.get("rewards", {}).get("reward")
    exception = data.get("exception_info") or {}
    reason = verifier_reason(trial) if reward == 0.0 or exception else ""
    category, analysis, confidence = classify_failure(reward, exception, reason) if reward != 1.0 else (
        "通过", "输出通过本任务 verifier。该结果证明满足基准定义，不等于完成实验验证。", "高"
    )
    started = data.get("started_at")
    finished = data.get("finished_at")
    duration = None
    if started and finished:
        duration = (datetime.fromisoformat(finished.replace("Z", "+00:00")) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
    metrics = {}
    trajectory = trial / "agent" / "trajectory.json"
    if trajectory.is_file():
        metrics = load_json(trajectory).get("final_metrics") or {}
    prompt = metrics.get("total_prompt_tokens") or 0
    cached = metrics.get("total_cached_tokens") or 0
    completion = metrics.get("total_completion_tokens") or 0
    miss = max(0, prompt - cached)
    offpeak = cached / 1e6 * 0.003 + miss / 1e6 * 0.15 + completion / 1e6 * 0.6
    peak = cached / 1e6 * 0.006 + miss / 1e6 * 0.3 + completion / 1e6 * 1.2
    return {
        "task": data.get("source") or trial.name.split("__")[0],
        "trial": trial.name,
        "reward": reward,
        "exception": exception,
        "reason": reason,
        "category": category,
        "analysis": analysis,
        "confidence": confidence,
        "started": started,
        "finished": finished,
        "duration": duration,
        "prompt": prompt,
        "cached": cached,
        "completion": completion,
        "offpeak": offpeak,
        "peak": peak,
        "result_path": result_path.relative_to(ROOT).as_posix(),
        "log_path": (trial / "trial.log").relative_to(ROOT).as_posix(),
    }


def status_for(record: dict[str, Any] | None, hpc: bool, pointers: list[str], active: bool) -> tuple[str, str]:
    if record:
        if record["exception"]:
            return "异常", record["category"]
        if record["reward"] == 1.0:
            return "通过", record["category"]
        return "未通过", record["category"]
    if hpc:
        return "未测", "HPC 环境未配置"
    if pointers:
        return "未测", "缺少 LFS 科学输入"
    if active:
        return "进行中", "已进入 local 批次"
    return "未测", "未纳入本地批次"


def build_rows() -> list[dict[str, Any]]:
    job = ROOT / "jobs" / JOB_NAME
    records = {}
    if job.is_dir():
        for path in job.glob("*/result.json"):
            try:
                record = trial_record(path)
            except (json.JSONDecodeError, OSError):
                continue
            records[record["task"]] = record
    rows = []
    for task in sorted((ROOT / "tasks").iterdir()):
        if not task.is_dir():
            continue
        hpc = is_hpc(task)
        pointers = lfs_inputs(task)
        record = records.get(task.name)
        status, short_reason = status_for(record, hpc, pointers, bool(job.is_dir()))
        config = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
        row = {
            "task": task.name,
            "description": task_description(task),
            "scope": "HPC" if hpc else "Local",
            "status": status,
            "reason": short_reason,
            "record": record,
            "pointers": pointers,
            "timeout": config.get("agent", {}).get("timeout_sec"),
        }
        if record:
            row["reason"] = record["reason"] or short_reason
        rows.append(row)
    return rows


def select_cases(rows: list[dict[str, Any]], preferred: list[str], status: str, limit: int) -> list[dict[str, Any]]:
    selected = []
    for name in preferred:
        row = next((row for row in rows if row["task"] == name and row["status"] == status), None)
        if row:
            selected.append(row)
    for row in rows:
        if len(selected) >= limit:
            break
        if row["status"] == status and row not in selected:
            selected.append(row)
    return selected


def badge(label: str, kind: str) -> str:
    return f'<span class="badge {kind}">{html.escape(label)}</span>'


def render(rows: list[dict[str, Any]], partial: bool) -> str:
    total = len(rows)
    if total != EXPECTED_TASKS:
        raise ValueError(f"Expected {EXPECTED_TASKS} tasks, found {total}")
    counts = Counter(row["status"] for row in rows)
    scope = Counter(row["scope"] for row in rows)
    failures = Counter(
        row["record"]["category"] if row["record"] else row["reason"]
        for row in rows
        if row["status"] in {"未通过", "异常", "未测"}
    )
    records = [row["record"] for row in rows if row["record"]]
    prompt = sum(record["prompt"] for record in records)
    cached = sum(record["cached"] for record in records)
    completion = sum(record["completion"] for record in records)
    offpeak = sum(record["offpeak"] for record in records)
    peak = sum(record["peak"] for record in records)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    normal = counts["通过"] + counts["未通过"]
    pass_rate = counts["通过"] / normal * 100 if normal else 0
    scope_status = Counter((row["scope"], row["status"]) for row in rows)
    coverage_rows = []
    for scope_name in ("Local", "HPC"):
        for status_name in ("通过", "未通过", "异常", "未测", "进行中"):
            count = scope_status[scope_name, status_name]
            if count:
                coverage_rows.append(f'<tr><td>{scope_name}</td><td>{status_name}</td><td>{count}</td></tr>')
    scope_note = "本报告是全任务审计台账，不是纯通过率榜单。未测和异常不会被当作模型答错。"
    if partial:
        scope_note += " 当前批次尚未结束，页面标记为阶段性结果。"
    task_rows = []
    for row in rows:
        record = row["record"]
        reward = record["reward"] if record else None
        analysis = record["analysis"] if record else row["reason"]
        confidence = record["confidence"] if record else "高"
        evidence = "—"
        if record:
            evidence = f'<a href="../{record["result_path"]}">结果</a> · <a href="../{record["log_path"]}">日志</a>'
        pointer_note = ""
        if row["pointers"]:
            pointer_note = f'<div class="fine">LFS 指针：{html.escape(", ".join(row["pointers"][:2]))}</div>'
        display_reason = " ".join(row["reason"].split())
        if len(display_reason) > 260:
            display_reason = display_reason[:257] + "…"
        task_rows.append(
            f'<tr data-status="{row["status"]}" data-scope="{row["scope"]}" data-search="{html.escape(row["task"] + " " + row["description"], quote=True)}">'
            f'<td><strong>{row["task"]}</strong><div class="description">{html.escape(row["description"])}</div></td>'
            f'<td>{row["scope"]}</td><td>{badge(row["status"], row["status"])}</td>'
            f'<td>{"—" if reward is None else reward}</td><td>{format_duration(record["duration"] if record else None)}</td>'
            f'<td><strong>{html.escape(display_reason)}</strong><p>{html.escape(analysis)}</p>{pointer_note}<div class="fine">判断置信度：{confidence}</div></td>'
            f'<td class="evidence">{evidence}</td></tr>'
        )
    failure_rows = []
    for reason, count in failures.most_common():
        failure_rows.append(f'<tr><td>{html.escape(reason)}</td><td>{count}</td><td>{count / total * 100:.1f}%</td></tr>')
    cases = select_cases(rows, ["001-task001", "014-task014", "122-task122", "167-task167", "182-task182"], "通过", 3)
    cases += select_cases(rows, ["010-task010", "024-task024", "039-task039"], "未通过", 2)
    cases += select_cases(rows, ["042-task042", "062-task062"], "异常", 1)
    case_html = []
    for row in cases:
        record = row["record"]
        case_html.append(
            f'<article class="case"><div class="case-head"><strong>{row["task"]}</strong>{badge(row["status"], row["status"])}</div>'
            f'<p class="case-description">{html.escape(row["description"])}</p>'
            f'<p>{html.escape(record["analysis"])}</p><div class="fine">耗时：{format_duration(record["duration"])} · 置信度：{record["confidence"]}</div>'
            f'<a href="../{record["result_path"]}">查看结果</a> · <a href="../{record["log_path"]}">查看日志</a></article>'
        )
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CompChemWorld 本地测评审计报告</title>
<style>
:root{{--paper:#f4f7f8;--surface:#fff;--ink:#18323f;--muted:#607681;--line:#cbd8dc;--teal:#167c80;--gold:#a56818;--red:#b64b45;--blue:#376d9b;--grey:#7a858a}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:ui-sans-serif,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.65}}
a{{color:var(--teal);text-decoration-thickness:1px;text-underline-offset:3px}}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{{outline:3px solid var(--gold);outline-offset:3px}}
.hero{{background:var(--ink);color:#f4f7f8;padding:56px max(24px,5vw) 42px;border-bottom:6px solid var(--teal)}}
.hero-inner{{max-width:1440px;margin:auto}}h1{{font-family:ui-serif,"Songti SC","Noto Serif CJK SC",serif;font-size:clamp(34px,5vw,64px);font-weight:600;line-height:1.15;margin:0 0 18px;letter-spacing:-.02em}}.hero p{{max-width:760px;color:#d7e4e8;font-size:17px}}.meta{{font-size:13px;color:#b9ccd2;margin-top:24px}}
.wrap{{max-width:1440px;margin:auto;padding:34px max(20px,4vw) 64px}}h2{{font-family:ui-serif,"Songti SC","Noto Serif CJK SC",serif;font-size:28px;line-height:1.3;margin:0 0 18px}}section{{margin-top:48px}}.summary{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
.metric{{padding:22px 18px 22px 0;border-right:1px solid var(--line)}}.metric:last-child{{border-right:0}}.metric strong{{display:block;font-family:ui-serif,"Songti SC",serif;font-size:36px;font-weight:600;line-height:1.2}}.metric span{{color:var(--muted);font-size:13px}}.note{{background:#eaf1f2;border-left:4px solid var(--teal);padding:18px 22px;max-width:960px}}.note p{{margin:5px 0}}.warning{{border-left-color:var(--gold)}}
.table-wrap{{overflow:auto;background:var(--surface);border:1px solid var(--line)}}table{{border-collapse:collapse;width:100%;font-size:14px}}th{{text-align:left;color:var(--muted);font-weight:600;background:#edf2f3;position:sticky;top:0}}th,td{{padding:13px 14px;border-bottom:1px solid #dfe7e9;vertical-align:top}}td{{max-width:440px}}td p{{margin:5px 0 0;color:var(--muted)}}tr:last-child td{{border-bottom:0}}.description{{color:var(--muted);font-size:12px;max-width:270px;margin-top:4px}}.fine{{font-size:12px;color:var(--muted);margin-top:6px}}.evidence{{white-space:nowrap}}
.badge{{display:inline-block;padding:2px 9px;border:1px solid currentColor;border-radius:999px;font-size:12px;white-space:nowrap}}.badge.通过{{color:var(--teal);background:#e6f2f0}}.badge.未通过{{color:var(--red);background:#f9ecea}}.badge.异常{{color:var(--gold);background:#fbf2e3}}.badge.未测{{color:var(--grey);background:#eef1f2}}.badge.进行中{{color:var(--blue);background:#e9f0f7}}
.controls{{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 16px}}input,select{{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--line);padding:9px 12px;min-width:180px}}input{{flex:1;min-width:240px}}.count{{color:var(--muted);font-size:13px;align-self:center}}.costs{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}}.cost{{background:var(--surface);padding:20px}}.cost strong{{display:block;font-size:25px}}.cost span{{color:var(--muted);font-size:13px}}.cases{{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}}.case{{border-top:3px solid var(--teal);padding:16px 0}}.case-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.case-description{{color:var(--muted);font-size:13px}}.foot{{color:var(--muted);font-size:13px;max-width:900px;margin-top:36px}}
@media(max-width:900px){{.summary{{grid-template-columns:repeat(3,1fr)}}.metric{{border-bottom:1px solid var(--line)}}.costs{{grid-template-columns:1fr}}.cases{{grid-template-columns:1fr}}}}@media(max-width:520px){{.summary{{grid-template-columns:repeat(2,1fr)}}.hero{{padding-top:36px}}h1{{font-size:36px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
</style>
</head>
<body>
<header class="hero"><div class="hero-inner"><h1>本地测评审计报告</h1><p>CompChemWorld · 186 个任务 · 成功、失败、异常与漏测的同一份证据台账</p><div class="meta">生成于 {generated} · 数据源：jobs/{JOB_NAME}</div></div></header>
<main class="wrap">
<section><h2>总体结论</h2><div class="summary">
<div class="metric"><strong>{total}</strong><span>任务总数</span></div><div class="metric"><strong>{scope['Local']}</strong><span>Local 任务</span></div><div class="metric"><strong>{scope['HPC']}</strong><span>HPC 任务</span></div>
<div class="metric"><strong>{counts['通过']}</strong><span>通过</span></div><div class="metric"><strong>{counts['未通过'] + counts['异常']}</strong><span>未通过或异常</span></div><div class="metric"><strong>{counts['未测'] + counts['进行中']}</strong><span>未测或进行中</span></div>
</div><div class="note" style="margin-top:22px"><p>{scope_note}</p><p>正常结束任务的通过率：<strong>{pass_rate:.1f}%</strong>（{counts['通过']} / {normal}）。HPC 仅审计、不运行；未测任务不会被计入模型答错。</p></div></section>
<section><h2>范围与状态交叉核对</h2><div class="table-wrap"><table><thead><tr><th>范围</th><th>状态</th><th>任务数</th></tr></thead><tbody>{''.join(coverage_rows)}</tbody></table></div></section>
<section><h2>失败与漏测原因</h2><div class="table-wrap"><table><thead><tr><th>原因分类</th><th>任务数</th><th>占全部任务</th></tr></thead><tbody>{''.join(failure_rows)}</tbody></table></div></section>
<section><h2>Token 与费用估算</h2><div class="costs"><div class="cost"><strong>{prompt / 1e6:.2f} M</strong><span>输入 token，其中 {cached / 1e6:.2f} M 命中缓存</span></div><div class="cost"><strong>{completion / 1e6:.2f} M</strong><span>输出 token</span></div><div class="cost"><strong>${offpeak:.2f} / ${peak:.2f}</strong><span>非高峰 / 高峰估算</span></div></div><p class="fine">按 DeepSeek 官方缓存输入、未缓存输入和输出价格计算，不使用 Claude 价格字段。仅包含已有模型轨迹的实际用量。</p></section>
<section><h2>成功与失败案例</h2><div class="cases">{''.join(case_html)}</div></section>
<section><h2>全部任务审计台账</h2><div class="controls"><input id="q" type="search" placeholder="搜索任务编号或描述" aria-label="搜索任务"><select id="status" aria-label="按状态筛选"><option value="">全部状态</option>{''.join(f'<option>{name}</option>' for name in ('通过','未通过','异常','未测','进行中'))}</select><select id="scope" aria-label="按范围筛选"><option value="">Local + HPC</option><option>Local</option><option>HPC</option></select><span class="count" id="count"></span></div>
<div class="table-wrap"><table><thead><tr><th>任务与说明</th><th>范围</th><th>状态</th><th>Reward</th><th>耗时</th><th>原因与解读</th><th>证据</th></tr></thead><tbody id="tasks">{''.join(task_rows)}</tbody></table></div></section>
<footer class="foot">报告中的“模型科学判断”与“输出结构”分类依据 verifier 返回的具体证据；无法可靠区分的项目保留为待复核，不把基础设施异常误算成模型能力不足。</footer>
</main>
<script>
const q=document.querySelector('#q'),status=document.querySelector('#status'),scope=document.querySelector('#scope'),rows=[...document.querySelectorAll('#tasks tr')];
function filter(){{const query=q.value.toLowerCase();let visible=0;for(const row of rows){{const show=(!status.value||row.dataset.status===status.value)&&(!scope.value||row.dataset.scope===scope.value)&&(!query||row.dataset.search.toLowerCase().includes(query));row.hidden=!show;if(show)visible++;}}document.querySelector('#count').textContent=`显示 ${{visible}} / ${{rows.length}} 个任务`;}}
[q,status,scope].forEach(el=>el.addEventListener('input',filter));filter();
</script>
</body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    rows = build_rows()
    partial = any(row["status"] == "进行中" for row in rows)
    if partial and not args.allow_partial:
        raise SystemExit("The local batch is still running; use --allow-partial for a draft report.")
    output = ROOT / "output" / "report.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(rows, partial), encoding="utf-8")
    counts = Counter(row["status"] for row in rows)
    print(f"Wrote {output}")
    print(f"Tasks: {len(rows)}; " + ", ".join(f"{key}: {value}" for key, value in sorted(counts.items())))


if __name__ == "__main__":
    main()
