"""包含四个专注型只读页面的 Streamlit 运维控制台。

Streamlit 采用延迟导入，使只安装 API 和测试依赖的机器仍可使用核心包和 CLI。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

PAGE_NAMES = (
    "知识检索",
    "事故场景回放",
    "配置差异比较",
    "追踪与评测",
)


@dataclass(slots=True)
class PageServices:
    """显式 UI 回调；处理器必须是只读应用服务。"""

    scenario_replay: Callable[[str], Any] | None = None
    knowledge_query: Callable[[Any], Any] | None = None
    configuration_diff: Callable[[str, str, str], Any] | None = None
    trace_evaluation: Callable[[], Any] | None = None

    @classmethod
    def from_container(cls, container: Any) -> PageServices:
        """将应用层服务容器适配为页面回调。"""
        if isinstance(container, cls):
            return container
        handlers = container.ui_handlers()
        return cls(
            scenario_replay=handlers.get("scenario_replay"),
            knowledge_query=handlers.get("knowledge_query"),
            configuration_diff=handlers.get("configuration_diff"),
            trace_evaluation=handlers.get("trace_evaluation"),
        )


def render(services: Any = None) -> None:
    """在 ``streamlit run`` 调用时渲染运维控制台。"""
    try:
        import streamlit as st  # Streamlit 是可选依赖。
    except ImportError as error:  # pragma: no cover  # 仅部署环境会触发，核心测试不覆盖。
        raise RuntimeError("Streamlit 界面是可选依赖，请单独安装 streamlit 后再运行") from error

    configured = (
        PageServices.from_container(services)
        if services is not None and not isinstance(services, PageServices)
        else services or PageServices()
    )
    _configure_page(st)
    _render_sidebar(st)
    st.markdown(
        "<header class='appbar'><div class='appbar-brand'><span class='brand-mark'>N</span>"
        "<span><strong>NETOPS COPILOT</strong><small>Evidence operations console</small></span></div>"
        "<div class='appbar-state'><span class='live-dot'></span><span>LOCAL-MILVUS</span>"
        "<span class='state-divider'></span><span>只读模式</span></div></header>",
        unsafe_allow_html=True,
    )
    page = st.session_state.get("active_page") or PAGE_NAMES[0]
    page = st.sidebar.radio("工作区", PAGE_NAMES, index=PAGE_NAMES.index(page), label_visibility="collapsed")
    st.session_state["active_page"] = page
    if page == "知识检索":
        render_knowledge_query(st, configured)
    elif page == "事故场景回放":
        render_scenario_replay(st, configured)
    elif page == "配置差异比较":
        render_configuration_diff(st, configured)
    else:
        render_trace_evaluation(st, configured)


def _render_sidebar(st: Any) -> None:
    st.sidebar.markdown(
        "<div class='sidebar-brand'><div class='sidebar-brand-mark'>N</div>"
        "<div><strong>NETWORK OPS</strong><span>Knowledge workspace</span></div></div>"
        "<div class='sidebar-label'>工作台</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "<div class='sidebar-signal'><span class='signal-line'><span class='live-dot'></span>检索链路在线</span>"
        "<span class='signal-detail'>Milvus / PostgreSQL / 云端 Embedding</span></div>",
        unsafe_allow_html=True,
    )


def render_scenario_replay(st: Any, services: PageServices) -> None:
    _render_secondary_header(st, "INCIDENT REPLAY", "事故场景回放", "回放固定的事故检索结果包，不执行设备变更。")
    scenario_labels = {
        "OSPF ExStart": "OSPF ExStart（邻居建立阶段）",
        "ACL outage": "ACL 故障",
        "LACP mismatch": "LACP 参数不一致",
        "L2 loop": "二层环路",
        "Optical flap": "光模块链路抖动",
    }
    scenario = st.selectbox(
        "事故场景",
        tuple(scenario_labels),
        format_func=lambda value: scenario_labels[value],
    )
    if st.button("回放检索结果", type="primary"):
        _render_result(st, services.scenario_replay(scenario) if services.scenario_replay else None)


def render_knowledge_query(st: Any, services: PageServices) -> None:
    st.markdown(
        "<div class='page-kicker'>KNOWLEDGE OPERATIONS</div>"
        "<div class='page-title-row'><div><h1>知识检索与引用问答</h1>"
        "<p class='page-subtitle'>把运维问题交给检索链路，模型只基于本次返回的检索结果作答。</p></div>"
        "<div class='readonly-badge'><span class='live-dot'></span>检索结果优先 · 默认只读</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='signal-strip'><div><span class='strip-label'>ACTIVE INDEX</span>"
        "<strong>Milvus Dense + BM25</strong></div><div><span class='strip-label'>ANSWER POLICY</span>"
        "<strong>引用不足则不回答</strong></div><div><span class='strip-label'>ACCESS</span>"
        "<strong>只读运维工作流</strong></div></div>",
        unsafe_allow_html=True,
    )
    with st.form("knowledge-query-form", clear_on_submit=False):
        st.markdown("<div class='form-kicker'>ASK THE KNOWLEDGE BASE</div>", unsafe_allow_html=True)
        query = st.text_area(
            "运维问题",
            placeholder="例如：OSPF ExStart 状态需要检查哪些内容？",
            height=86,
            label_visibility="collapsed",
        )
        settings = st.columns((1.2, 1.0, 1.0, 0.8))
        mode_labels = {
            "hybrid": "混合检索",
            "dense-only": "语义检索",
            "lexical-only": "关键词检索",
        }
        model_labels = {"dashscope": "云端模型", "local": "本地模型"}
        with settings[0]:
            mode = st.selectbox(
                "检索方式",
                tuple(mode_labels),
                format_func=lambda value: mode_labels[value],
            )
        with settings[1]:
            rerank = st.checkbox("启用重排", value=True, help="混合检索下使用确定性词项覆盖率重排")
        with settings[2]:
            model_source = st.selectbox(
                "回答模型",
                tuple(model_labels),
                format_func=lambda value: model_labels[value],
            )
        with settings[3]:
            limit = st.slider("Top-K", min_value=1, max_value=10, value=5)
        submitted = st.form_submit_button("生成带引用的回答", type="primary", use_container_width=True)
    if submitted:
        if not query.strip():
            st.warning("请先输入运维问题。")
        elif services.knowledge_query is None:
            st.error("知识问答服务未配置，请先启动 local-milvus 运行时。")
        else:
            try:
                result = services.knowledge_query(
                    {
                        "query": query,
                        "mode": mode,
                        "rerank": rerank,
                        "model_source": model_source,
                        "limit": limit,
                    }
                )
            except (RuntimeError, ValueError) as error:
                st.error(str(error))
            else:
                st.session_state["knowledge_result"] = result
    result = st.session_state.get("knowledge_result")
    if result is not None:
        _render_answer(st, result)
    else:
        _render_knowledge_empty_state(st)


def _render_knowledge_empty_state(st: Any) -> None:
    st.markdown(
        "<section class='empty-state'><div class='empty-orbit'><span></span><span></span><span></span></div>"
        "<div><div class='empty-kicker'>READY FOR A QUESTION</div><h2>以检索结果作为根本依据。</h2>"
        "<p>输入网络、设备或故障现象，系统会返回可追溯的运维判断与原文依据。</p></div></section>",
        unsafe_allow_html=True,
    )
    st.markdown("<div class='section-kicker'>常用问题</div>", unsafe_allow_html=True)
    cards = st.columns(3)
    prompts = (
        ("链路状态", "OSPF ExStart 需要检查哪些内容？"),
        ("配置核对", "LACP 参数不一致时如何确认？"),
        ("安全策略", "ACL 故障应该先检查哪些检索结果？"),
    )
    for column, (label, prompt) in zip(cards, prompts, strict=True):
        with column:
            st.markdown(
                f"<div class='prompt-card'><span>{label}</span><strong>{prompt}</strong>"
                "<small>在上方输入框中开始检索</small></div>",
                unsafe_allow_html=True,
            )


def render_configuration_diff(st: Any, services: PageServices) -> None:
    _render_secondary_header(st, "CONFIGURATION REVIEW", "配置差异比较", "对比两份配置快照，输出确定性差异与风险提示。")
    vendors = ("Huawei", "H3C", "Ruijie", "Cisco")
    vendor_labels = {"Huawei": "华为", "H3C": "H3C", "Ruijie": "锐捷", "Cisco": "思科"}
    vendor = st.selectbox("厂商", vendors, format_func=lambda value: vendor_labels[value])
    baseline = st.text_area("基线配置快照", height=180)
    current = st.text_area("当前配置快照", height=180)
    if st.button("计算确定性差异", type="primary"):
        if not baseline.strip() or not current.strip():
            st.warning("请同时填写基线配置和当前配置。")
        else:
            result = services.configuration_diff(vendor, baseline, current) if services.configuration_diff else None
            _render_result(st, result)


def render_trace_evaluation(st: Any, services: PageServices) -> None:
    _render_secondary_header(st, "TRACE & EVALUATION", "追踪与评测", "查看处理阶段、降级标记和基线指标。")
    if st.button("加载最新报告", type="primary"):
        _render_result(st, services.trace_evaluation() if services.trace_evaluation else None)


def _render_secondary_header(st: Any, kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"<div class='page-kicker'>{kicker}</div><div class='page-title-row'>"
        f"<div><h1>{title}</h1><p class='page-subtitle'>{subtitle}</p></div>"
        "<div class='readonly-badge'><span class='live-dot'></span>只读工作流</div></div>",
        unsafe_allow_html=True,
    )


def _configure_page(st: Any) -> None:
    st.set_page_config(
        page_title="Network Operations Copilot",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root { --bg: #07131d; --bg-2: #0a1d2a; --panel: #0d2230; --panel-2: #102b3a; --line: #1d4050; --line-soft: rgba(128,190,204,.16); --ink: #edf6f7; --muted: #91aeb8; --accent: #65d8c5; --accent-2: #9cebdd; --warm: #eab56b; --danger: #ef8f85; }
        .stApp { background: radial-gradient(circle at 86% -8%, #1c4654 0, var(--bg-2) 28%, var(--bg) 68%); color: var(--ink); font-family: "Aptos", "Segoe UI", sans-serif; }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stToolbar"] { visibility: hidden; }
        [data-testid="stSidebar"] { background: #081923; border-right: 1px solid var(--line-soft); }
        [data-testid="stSidebar"] > div:first-child { background: linear-gradient(180deg, #0a1c28 0%, #07151e 100%); }
        .block-container { max-width: 1480px; padding: 1.65rem 2.5rem 5.5rem; }
        .appbar { display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line-soft); padding:0 0 1rem; margin-bottom:2.6rem; }
        .appbar-brand,.appbar-state,.sidebar-brand,.signal-line { display:flex; align-items:center; }
        .appbar-brand { gap:.7rem; color:var(--ink); }
        .appbar-brand strong { display:block; font-size:.76rem; letter-spacing:.16em; }
        .appbar-brand small { display:block; margin-top:.2rem; color:var(--muted); font-size:.68rem; letter-spacing:.04em; }
        .brand-mark,.sidebar-brand-mark { display:grid; place-items:center; border:1px solid rgba(101,216,197,.58); background:rgba(101,216,197,.08); color:var(--accent-2); font-weight:800; }
        .brand-mark { width:2rem; height:2rem; border-radius:9px; font-size:.86rem; }
        .appbar-state { gap:.6rem; color:var(--muted); font-family:"Cascadia Mono", monospace; font-size:.66rem; letter-spacing:.08em; }
        .state-divider { width:1px; height:15px; background:var(--line); }
        .live-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 4px rgba(101,216,197,.11); }
        .sidebar-brand { gap:.7rem; padding:.45rem .3rem 1.9rem; }
        .sidebar-brand-mark { width:2.25rem; height:2.25rem; border-radius:11px; }
        .sidebar-brand strong { display:block; font-size:.74rem; letter-spacing:.14em; }
        .sidebar-brand span { display:block; margin-top:.22rem; color:var(--muted); font-size:.68rem; }
        .sidebar-label,.section-kicker,.page-kicker,.form-kicker,.empty-kicker { color:var(--accent); font-size:.65rem; font-weight:800; letter-spacing:.15em; }
        .sidebar-label { margin:0 .3rem .55rem; color:#6f8e99; }
        .sidebar-signal { margin:2rem .3rem 0; padding:.85rem .8rem; border:1px solid var(--line-soft); border-radius:13px; background:rgba(13,34,48,.56); }
        .signal-line { gap:.55rem; color:var(--ink); font-size:.75rem; font-weight:700; }
        .signal-detail { display:block; margin-top:.45rem; color:var(--muted); font-size:.66rem; line-height:1.45; }
        [data-testid="stSidebar"] [data-testid="stRadio"] label { padding:.58rem .7rem; border-radius:9px; color:#99b4bd; font-size:.84rem; transition:background .18s ease, color .18s ease; }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:rgba(101,216,197,.08); color:var(--ink); }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) { background:rgba(101,216,197,.12); color:var(--accent-2); }
        .page-kicker { margin-bottom:.6rem; }
        .page-title-row { display:flex; align-items:end; justify-content:space-between; gap:1.5rem; margin-bottom:1.45rem; }
        .page-title-row h1 { margin:0; color:var(--ink); font-size:clamp(2rem, 4vw, 3.65rem); letter-spacing:-.045em; line-height:1.02; }
        .page-subtitle { max-width:720px; margin:.7rem 0 0; color:var(--muted); font-size:.96rem; line-height:1.65; }
        .readonly-badge { display:flex; align-items:center; gap:.55rem; white-space:nowrap; padding:.55rem .7rem; border:1px solid var(--line); border-radius:10px; color:#b9ccd1; font-size:.7rem; }
        .signal-strip { display:grid; grid-template-columns:repeat(3,1fr); gap:1px; margin:1rem 0 1.25rem; border:1px solid var(--line-soft); border-radius:14px; overflow:hidden; background:var(--line-soft); }
        .signal-strip > div { padding:.82rem 1rem; background:rgba(11,31,43,.82); }
        .strip-label { display:block; color:#6f909a; font-family:"Cascadia Mono", monospace; font-size:.59rem; letter-spacing:.12em; }
        .signal-strip strong { display:block; margin-top:.32rem; color:#dbecee; font-size:.78rem; font-weight:600; }
        [data-testid="stForm"] { border:1px solid rgba(101,216,197,.27); border-radius:17px; padding:1.25rem 1.25rem .7rem; background:linear-gradient(135deg,rgba(15,43,57,.92),rgba(9,26,37,.9)); box-shadow:0 20px 50px rgba(0,0,0,.16); }
        .form-kicker { margin-bottom:.65rem; color:#82cfc4; }
        textarea, input { color:var(--ink) !important; }
        textarea { border-radius:11px !important; border-color:rgba(128,190,204,.24) !important; background:rgba(5,18,27,.6) !important; line-height:1.55 !important; }
        textarea:focus { border-color:var(--accent) !important; box-shadow:0 0 0 1px var(--accent) !important; }
        [data-testid="stTextAreaRootElement"] { background:rgba(5,18,27,.9) !important; border:1px solid rgba(128,190,204,.32) !important; border-radius:11px !important; }
        [data-testid="stTextArea"] textarea { background:transparent !important; color:var(--ink) !important; }
        div[data-baseweb="select"] > div { background:rgba(5,18,27,.9) !important; border:1px solid rgba(128,190,204,.32) !important; color:var(--ink) !important; }
        div[data-baseweb="select"] > div > div { background:transparent !important; color:var(--ink) !important; }
        div[data-baseweb="select"] [role="combobox"], div[data-baseweb="select"] [role="combobox"] * { color:var(--ink) !important; }
        div[data-baseweb="select"] svg { fill:var(--accent-2) !important; color:var(--accent-2) !important; }
        .react-aria-ComboBox > [role="group"] { background:rgba(5,18,27,.9) !important; border:1px solid rgba(128,190,204,.32) !important; border-radius:11px !important; }
        .react-aria-ComboBox input { background:transparent !important; color:var(--ink) !important; caret-color:var(--accent) !important; }
        .react-aria-ComboBox input::placeholder { color:#7898a2 !important; opacity:1 !important; }
        .react-aria-ComboBox button { background:transparent !important; color:var(--accent-2) !important; }
        .react-aria-ComboBox button svg { fill:var(--accent-2) !important; }
        [data-testid="stSelectbox"] label, [data-testid="stCheckbox"] label, [data-testid="stSlider"] label { color:var(--muted) !important; }
        [data-testid="stCheckbox"] label p { color:var(--ink) !important; }
        [data-baseweb="popover"] [role="listbox"] { background:var(--panel-2) !important; border:1px solid var(--line) !important; }
        [data-baseweb="popover"] [role="option"], [data-baseweb="popover"] [role="option"] * { color:var(--ink) !important; }
        [data-baseweb="popover"] [role="option"][aria-selected="true"] { background:rgba(101,216,197,.16) !important; }
        [data-testid="stSlider"] [role="slider"] { background:var(--accent) !important; }
        [data-testid="stFormSubmitButton"] button, .stButton > button { min-height:2.55rem; border-radius:9px; border:1px solid rgba(101,216,197,.38); font-weight:700; }
        [data-testid="stFormSubmitButton"] button { background:var(--accent); color:#06202a; }
        [data-testid="stFormSubmitButton"] button:hover { background:var(--accent-2); border-color:var(--accent-2); box-shadow:0 9px 25px rgba(101,216,197,.16); }
        .stButton > button:hover { border-color:var(--accent); color:var(--accent-2); transform:translateY(-1px); }
        div[data-testid="stMetric"] { min-height:78px; padding:.8rem .9rem; border:1px solid var(--line-soft); border-radius:12px; background:rgba(13,34,48,.74); }
        div[data-testid="stMetricLabel"] { color:#7898a2; }
        div[data-testid="stMetricValue"] { color:var(--ink); font-family:"Cascadia Mono", monospace; font-size:1.1rem; }
        .empty-state { display:flex; align-items:center; gap:2.1rem; min-height:190px; margin-top:1.8rem; padding:2rem; border:1px solid var(--line-soft); border-radius:17px; background:linear-gradient(135deg,rgba(14,42,56,.66),rgba(8,23,33,.72)); }
        .empty-state h2 { margin:.45rem 0 .45rem; font-size:1.65rem; letter-spacing:-.035em; }
        .empty-state p { max-width:590px; margin:0; color:var(--muted); line-height:1.65; font-size:.86rem; }
        .empty-orbit { position:relative; width:92px; height:92px; flex:0 0 92px; border:1px solid rgba(101,216,197,.38); border-radius:50%; }
        .empty-orbit:before,.empty-orbit:after { content:""; position:absolute; inset:13px; border:1px solid rgba(101,216,197,.18); border-radius:50%; }
        .empty-orbit:after { inset:28px; border-color:rgba(234,181,107,.35); }
        .empty-orbit span { position:absolute; width:7px; height:7px; border-radius:50%; background:var(--accent); }
        .empty-orbit span:nth-child(1) { top:8px; left:42px; }
        .empty-orbit span:nth-child(2) { right:8px; bottom:26px; background:var(--warm); }
        .empty-orbit span:nth-child(3) { left:17px; bottom:12px; background:var(--accent-2); }
        .section-kicker { margin:2rem 0 .75rem; color:#7596a0; }
        .prompt-card { min-height:120px; padding:1rem; border:1px solid var(--line-soft); border-radius:13px; background:rgba(13,34,48,.65); transition:transform .18s ease, border-color .18s ease, background .18s ease; }
        .prompt-card:hover { transform:translateY(-2px); border-color:rgba(101,216,197,.47); background:rgba(16,43,58,.9); }
        .prompt-card span,.prompt-card small { display:block; color:#75a7aa; font-size:.66rem; }
        .prompt-card strong { display:block; margin:.55rem 0 .7rem; color:#dcebed; font-size:.82rem; line-height:1.4; font-weight:600; }
        .prompt-card small { color:#6d8993; }
        .answer-surface { margin-top:1.6rem; padding:1.35rem 1.45rem; border:1px solid rgba(101,216,197,.27); border-radius:17px; background:linear-gradient(135deg,rgba(14,46,57,.88),rgba(9,26,37,.92)); }
        .answer-surface h2 { margin:.25rem 0 1rem; font-size:1.22rem; letter-spacing:-.02em; }
        .answer-meta { display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:.45rem; color:#79aaa9; font-family:"Cascadia Mono", monospace; font-size:.63rem; letter-spacing:.08em; }
        .answer-text { color:#e6f1f1; font-size:1rem; line-height:1.78; }
        .evidence-heading { display:flex; align-items:end; justify-content:space-between; margin:1.8rem 0 .7rem; }
        .evidence-heading h2 { margin:0; font-size:1.05rem; }
        .evidence-heading span { color:var(--muted); font-family:"Cascadia Mono", monospace; font-size:.65rem; }
        div[data-testid="stExpander"] { border:1px solid var(--line-soft); border-radius:12px; background:rgba(13,34,48,.66); transition:transform .18s ease, border-color .18s ease; }
        div[data-testid="stExpander"]:hover { transform:translateY(-2px); border-color:rgba(101,216,197,.55); }
        .secondary-page { max-width:900px; }
        @media (max-width: 900px) { .block-container { padding:1.2rem 1.05rem 4rem; } .page-title-row { align-items:start; flex-direction:column; } .readonly-badge { align-self:flex-start; } .signal-strip { grid-template-columns:1fr; } .empty-state { align-items:flex-start; flex-direction:column; gap:1.1rem; } .appbar-state { display:none; } }
        @media (prefers-reduced-motion: reduce) { *, *:before, *:after { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_answer(st: Any, result: Any) -> None:
    if not isinstance(result, Mapping):
        _render_result(st, result)
        return
    status = str(result.get("status", ""))
    status_labels = {
        "success": "ANSWER READY",
        "no-evidence": "NO EVIDENCE",
        "model-unavailable": "MODEL UNAVAILABLE",
        "model-error": "MODEL ERROR",
    }
    status_label = status_labels.get(status, "ANSWER STATUS")
    st.markdown(
        f"<div class='answer-surface'><div class='answer-meta'><span>{status_label}</span>"
        f"<span>{result.get('model', '—')}</span></div><h2>运维判断</h2></div>",
        unsafe_allow_html=True,
    )
    st.markdown(str(result.get("answer", "")))
    retrieval = result.get("retrieval")
    if isinstance(retrieval, Mapping):
        metrics = st.columns(4)
        metrics[0].metric("检索", str(retrieval.get("mode", "-")))
        metrics[1].metric("检索结果", str(retrieval.get("candidate_count", 0)))
        metrics[2].metric("状态", str(retrieval.get("state", "-")))
        metrics[3].metric("模型", str(result.get("model", "-")))
        degradation = retrieval.get("degradation") or []
        if degradation:
            st.caption("降级提示：" + "；".join(str(item) for item in degradation))
    citations = result.get("citations") or []
    st.markdown(
        f"<div class='evidence-heading'><h2>检索结果来源</h2><span>{len(citations)} SOURCES / TRACEABLE</span></div>",
        unsafe_allow_html=True,
    )
    if not citations:
        st.info("本次没有可展开的引用检索结果。")
        return
    columns = st.columns(2)
    for index, citation in enumerate(citations):
        if not isinstance(citation, Mapping):
            continue
        number = citation.get("number", "?")
        locator = citation.get("source_locator") or citation.get("source_id") or citation.get("chunk_id")
        with columns[index % 2], st.expander(f"[{number}] {locator}"):
            st.caption(
                f"chunk_id: {citation.get('chunk_id', '')}  |  "
                f"source_id: {citation.get('source_id', '')}"
            )
            st.write(citation.get("excerpt", ""))


def _render_result(st: Any, result: Any) -> None:
    if result is None:
        st.info("当前演示未配置应用服务。")
    elif isinstance(result, Mapping):
        st.json(dict(result))
    else:
        st.write(result)


def main() -> None:
    render()


__all__ = ["PAGE_NAMES", "PageServices", "main", "render"]


if __name__ == "__main__":
    main()
