# agent.py
"""
Phase 3: a LangGraph agent that routes questions across three tools --
RAG Q&A, sentiment lookup, price data -- and composes a single answer.
 
Graph (per the completion guide, Section 4.3):
  START -> router (LLM: which tool, what args, or finished?)
  router -> tool (dispatches to whichever tool the router picked)
  tool -> router (loop: does the router want another tool?)
  router -> synthesiser (LLM: compose one answer from everything gathered)
  synthesiser -> END
 
Capped at MAX_ITERATIONS router/tool round-trips -- an agent that can loop
must also be able to be MADE to stop; this is that guarantee, not a nice-to-have.
 
Design choice worth being explicit about: the router uses a plain prompt
asking Gemini to return JSON, not google-genai's native function-calling API.
I can't verify the exact live function-calling schema from this environment
(same network constraint that blocked live-testing yfinance/HuggingFace) --
getting that subtly wrong silently would be worse than a simpler, fully
testable pattern. Native function-calling is a reasonable upgrade once this
can be tested against the real API.
 
The three tools wrap ALREADY-BUILT, already-tested functionality -- this file
adds no new data logic, only the routing/composition layer on top:
  rag_answer      -> rag.answer()               (Phase 1)
  sentiment_lookup -> ingestion.get_recent()      (existing corpus retrieval)
  price_fetch     -> yfinance, via the SAME resolved ticker map backtest.py
                     uses (ticker_map.json) -- not a second, separate
                     ticker-guessing mechanism.
 
Usage:
  python agent.py "Did the negative news on Vodafone Idea hurt the stock?"
"""
 
from __future__ import annotations
 
import os
import sys
import json
import logging
from typing import TypedDict
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
from langgraph.graph import StateGraph, START, END
 
import config
 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("agent")
 
GEMINI_MODEL_NAME = "gemini-3.5-flash"
MAX_ITERATIONS = 4  # per the guide's Day 10 spec -- a hard cap on router<->tool round-trips
 
 
# ═══════════════════════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════════════════════
 
class AgentState(TypedDict):
    question: str
    tool_calls_made: list[dict]   # [{"tool": str, "args": dict, "result": str}, ...]
    iteration: int
    next_action: dict | None      # the router's most recent decision
    final_answer: str | None
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Tools -- each wraps existing, already-tested code. No new data logic here.
# ═══════════════════════════════════════════════════════════════════════════
 
def rag_answer_tool(question: str, stock: str | None = None,
                    sector: str | None = None, days: int | None = None) -> str:
    """Qualitative why/what-happened questions, grounded with citations from the news corpus."""
    import rag
    result = rag.answer(question, stock=stock, sector=sector, days=days)
    if not result["sources"]:
        return result["answer"]
    sources_str = "; ".join(f"[{i+1}] {s['headline']} ({s['date']})"
                            for i, s in enumerate(result["sources"]))
    return f"{result['answer']}\n\nSources: {sources_str}"
 
 
def sentiment_lookup_tool(stock: str | None = None, sector: str | None = None,
                          days: int = 7) -> str:
    """Current average VADER and FinBERT sentiment for a stock or sector over a recent window."""
    import ingestion
    articles = ingestion.get_recent(stock=stock, sector=sector, days=days, limit=500)
    if not articles:
        target = stock or sector or "the corpus"
        return f"No recent articles found for {target} in the last {days} days."
 
    vader_scores = [a.vader_score for a in articles if a.vader_score is not None]
    finbert_scores = [a.finbert_continuous for a in articles if a.finbert_continuous is not None]
    vader_str = f"{sum(vader_scores)/len(vader_scores):.3f}" if vader_scores else "N/A"
    finbert_str = f"{sum(finbert_scores)/len(finbert_scores):.3f}" if finbert_scores else "N/A"
 
    target = stock or sector
    return (f"Sentiment for {target} over the last {days} days, {len(articles)} articles: "
           f"VADER avg={vader_str}, FinBERT avg={finbert_str} (both on a -1 to +1 scale).")
 
 
def _load_agent_ticker_map() -> dict:
    """Same ticker_map.json backtest.py builds via resolve_tickers.py --
    one resolved-ticker source of truth, not a second guessing mechanism here."""
    path = os.path.join(PROJECT_ROOT, "ticker_map.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)
 
 
def price_fetch_tool(stock: str, period: str = "1mo") -> str:
    """
    Recent price movement for a stock, reported as RETURNS (percentage change),
    not raw price levels -- per the guide's own methodology point: raw levels
    conflate genuine movement with whatever a stock's price happens to be.
    """
    import yfinance as yf
    ticker_map = _load_agent_ticker_map()
    resolved = ticker_map.get(stock)
    if not resolved:
        return (f"No resolved ticker for '{stock}' -- run resolve_tickers.py first "
               f"to build ticker_map.json.")
 
    df = yf.download(resolved, period=period, progress=False, auto_adjust=True)
    if df.empty:
        return f"No price data found for {stock} ({resolved}) over {period}."
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)
 
    close = df["Close"].squeeze()
    total_return = (close.iloc[-1] / close.iloc[0] - 1) * 100
    daily_returns = close.pct_change(fill_method=None).dropna()
    volatility = daily_returns.std() * 100
 
    return (f"{stock} over {period}: total return {total_return:+.2f}%, "
           f"daily volatility {volatility:.2f}%.")
 
 
TOOLS = {
    "rag_answer": rag_answer_tool,
    "sentiment_lookup": sentiment_lookup_tool,
    "price_fetch": price_fetch_tool,
}
 
TOOL_DESCRIPTIONS = """
- rag_answer(question, stock?, sector?, days?): qualitative why/what-happened questions,
  grounded with citations from the news corpus. Use for "why did X happen", "what's the
  risk with Y", "what did analysts say about Z".
- sentiment_lookup(stock?, sector?, days?): current average sentiment (VADER + FinBERT)
  for a stock or sector. Use for "how is sentiment on X", "most negative sector this week".
- price_fetch(stock, period?): recent price RETURN (percentage change) and volatility,
  not raw price levels. Use for "how has X moved", "did the stock go up or down".
"""
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Router and synthesiser -- the two LLM-calling nodes
# ═══════════════════════════════════════════════════════════════════════════
 
def _call_gemini(prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(model=GEMINI_MODEL_NAME, contents=prompt)
    return (response.text or "").strip()
 
 
def _parse_json_response(raw: str) -> dict:
    """Strips markdown code fences Gemini sometimes wraps JSON in, before parsing."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())
 
 
def router_node(state: AgentState) -> dict:
    tool_results_str = "\n".join(
        f"- {tc['tool']}({tc['args']}) -> {tc['result']}" for tc in state["tool_calls_made"]
    ) or "(none yet)"
 
    prompt = f"""You are the router for a financial analysis agent with these tools:
{TOOL_DESCRIPTIONS}
 
Question: {state['question']}
 
Tool results gathered so far:
{tool_results_str}
 
Decide the next action. Respond with ONLY a JSON object, no other text:
{{"action": "call_tool", "tool": "<tool_name>", "args": {{...}}}}
or, if you have enough information to answer:
{{"action": "finish"}}
"""
    raw = _call_gemini(prompt)
    try:
        decision = _parse_json_response(raw)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Router returned unparseable JSON, defaulting to finish: {raw!r} ({e})")
        decision = {"action": "finish"}
 
    return {"next_action": decision, "iteration": state["iteration"] + 1}
 
 
def tool_node(state: AgentState) -> dict:
    decision = state["next_action"]
    tool_name = decision.get("tool")
    args = decision.get("args", {})
 
    fn = TOOLS.get(tool_name)
    if fn is None:
        result = f"Unknown tool '{tool_name}' -- ignoring this call."
    else:
        try:
            result = fn(**args)
        except Exception as e:
            # Per the guide's Day 10 spec: tool errors return TEXT the router
            # can react to, not a crash -- the router sees this on the next
            # loop and can decide to try something else.
            result = f"Tool '{tool_name}' failed: {e}"
            logger.warning(f"Tool error: {result}")
 
    new_call = {"tool": tool_name, "args": args, "result": result}
    return {"tool_calls_made": state["tool_calls_made"] + [new_call]}
 
 
def synthesiser_node(state: AgentState) -> dict:
    tool_results_str = "\n".join(
        f"[{i+1}] {tc['tool']}({tc['args']}): {tc['result']}"
        for i, tc in enumerate(state["tool_calls_made"])
    ) or "(no tool results were gathered)"
 
    prompt = f"""Compose one clear answer to the question below, using the tool results
provided. Cite results as [1], [2] etc. matching their numbers. If the tool results
don't actually answer the question, say so honestly rather than guessing.
 
Question: {state['question']}
 
Tool results:
{tool_results_str}
 
Answer:"""
    answer = _call_gemini(prompt)
    return {"final_answer": answer}
 
 
def _route_after_router(state: AgentState) -> str:
    if state["iteration"] >= MAX_ITERATIONS:
        logger.info(f"Hit MAX_ITERATIONS={MAX_ITERATIONS}, forcing synthesis.")
        return "synthesiser"
    if state["next_action"].get("action") == "finish":
        return "synthesiser"
    return "tool"
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Graph assembly
# ═══════════════════════════════════════════════════════════════════════════
 
def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("tool", tool_node)
    graph.add_node("synthesiser", synthesiser_node)
 
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", _route_after_router,
                                {"tool": "tool", "synthesiser": "synthesiser"})
    graph.add_edge("tool", "router")
    graph.add_edge("synthesiser", END)
 
    return graph.compile()
 
 
_compiled_graph = None
 
 
def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
 
 
def answer_with_agent(question: str) -> dict:
    """Entry point -- runs the full graph, returns {"answer": str, "trace": [...]}."""
    initial_state: AgentState = {
        "question": question,
        "tool_calls_made": [],
        "iteration": 0,
        "next_action": None,
        "final_answer": None,
    }
    final_state = get_graph().invoke(initial_state)
    return {
        "answer": final_state["final_answer"],
        "trace": final_state["tool_calls_made"],
        "iterations": final_state["iteration"],
    }
 
 
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py \"<question>\"")
        sys.exit(1)
 
    question = sys.argv[1]
    result = answer_with_agent(question)
 
    print(f"\n=== Answer ===\n{result['answer']}")
    print(f"\n=== Tool call trace ({result['iterations']} router iterations) ===")
    for i, tc in enumerate(result["trace"], 1):
        print(f"{i}. {tc['tool']}({tc['args']})")
        print(f"   -> {tc['result'][:200]}")