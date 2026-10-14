import json, re, time
from urllib.parse import urlparse
from groq import Groq
from ddgs import DDGS
from .config import GROQ_API_KEY, GROQ_MODEL, MAX_SEARCH_RESULTS

class AgentError(RuntimeError):
    pass

def _clip(text: str, limit: int) -> str:
    return (text or '')[:limit]

def llm(system: str, user: str, temperature: float = 0.2, output_tokens: int = 450) -> str:
    if not GROQ_API_KEY:
        raise AgentError('GROQ_API_KEY is missing. Add it to backend/.env and restart the API.')
    # Conservative per-call input caps help avoid Groq TPM/context failures on free tiers.
    system, user = _clip(system, 900), _clip(user, 5200)
    try:
        response = Groq(api_key=GROQ_API_KEY, timeout=45, max_retries=1).chat.completions.create(
            model=GROQ_MODEL, temperature=temperature, max_completion_tokens=output_tokens,
            messages=[{'role':'system','content':system},{'role':'user','content':user}],
        )
        return (response.choices[0].message.content or '').strip()
    except Exception as exc:
        msg = str(exc)
        if 'tokens per minute' in msg.lower() or 'rate_limit' in msg.lower() or '413' in msg:
            raise AgentError('Groq token limit reached. ResearchPilot now limits prompts and snippets; wait about a minute, choose Quick scan, or reduce the question length, then retry.') from exc
        if 'model' in msg.lower() and ('not found' in msg.lower() or 'decommission' in msg.lower()):
            raise AgentError(f'Groq model "{GROQ_MODEL}" is unavailable for this API key. Choose an active model from https://console.groq.com/docs/models and update GROQ_MODEL in backend/.env.') from exc
        raise AgentError(f'Groq request failed: {msg[:500]}') from exc

def plan_research(question: str, depth: str, memory: str = '') -> list[str]:
    count = {'quick': 2, 'standard': 3, 'deep': 4}.get(depth, 3)
    raw = llm('Return only a JSON array of short web search queries. No markdown, no answer.',
              f'Question: {_clip(question, 500)}\nPrior context (optional): {_clip(memory, 250)}\nCreate {count} distinct queries: overview, evidence, trade-offs or limitations.', 0.1, 180)
    try:
        parsed = json.loads(raw[raw.find('['):raw.rfind(']') + 1])
        if isinstance(parsed, list) and parsed:
            items = [str(x).strip()[:130] for x in parsed if str(x).strip()]
            if items: return items[:count]
    except Exception: pass
    return [question[:130], f'{question[:90]} evidence and limitations'][:count]

def search_web(queries: list[str]) -> list[dict[str, str]]:
    items, seen = [], set()
    limit = min(MAX_SEARCH_RESULTS, 4)
    for query in queries[:4]:
        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=2)
        except Exception:
            continue
        for result in results or []:
            url = str(result.get('href') or result.get('url') or '').strip()
            if not url.startswith(('http://','https://')) or url in seen: continue
            seen.add(url)
            domain = urlparse(url).netloc.lower().removeprefix('www.')
            items.append({'title':str(result.get('title') or 'Untitled result')[:140], 'url':url[:400],
                          'domain':domain[:100], 'snippet':str(result.get('body') or result.get('snippet') or '')[:300]})
            if len(items) >= limit: return items
    return items

def score_sources(sources: list[dict]) -> dict:
    domains = {s.get('domain') or urlparse(s.get('url','')).netloc for s in sources}
    usable = sum(1 for s in sources if len(s.get('snippet','').strip()) >= 60 and s.get('url','').startswith('http'))
    return {'source_count':len(sources), 'distinct_domains':len(domains), 'usable_snippets':usable,
            'source_coverage':round(usable / max(1, len(sources)), 2),
            'evidence_note':'Heuristic source coverage; not a guarantee of source credibility.'}

def synthesize(question, plan, sources):
    evidence = '\n'.join(f"[S{i}] {s['title']} ({s.get('domain','')})\n{_clip(s['snippet'], 260)}" for i,s in enumerate(sources[:4],1))
    prompt = f'Question: {_clip(question,400)}\nQueries: {"; ".join(plan[:4])}\nEvidence snippets (not full pages):\n{evidence or "No web results found."}'
    return llm('Synthesize only the supplied snippets. Cite claims [S1], [S2]. Separate evidence from inference. Mention when evidence is insufficient. Maximum 350 words.', prompt, 0.2, 450)

def analyze(question, synthesis):
    return llm('Analyze the provided findings only. Identify themes, disagreement, limitations, missing evidence, and 2 follow-up questions. Maximum 220 words.',
               f'Question: {_clip(question,300)}\nFindings: {_clip(synthesis,1800)}', 0.2, 300)

def verify(question, synthesis, analysis, sources):
    evidence = '\n'.join(f"[S{i}] {s['title']}: {_clip(s['snippet'],180)}" for i,s in enumerate(sources[:4],1))
    prompt = f'Question: {_clip(question,250)}\nClaims to review: {_clip(synthesis,1400)}\nAnalysis: {_clip(analysis,650)}\nSnippets:\n{evidence}'
    return llm('Act as a skeptical reviewer. List up to 4 major claims and classify each Supported, Partially supported, or Unverified based only on snippets. Snippets do not prove full-page claims. Maximum 220 words.', prompt, 0.1, 300)

def write_report(question, synthesis, analysis, verification, sources):
    source_list = '\n'.join(f"- [S{i}] [{_clip(s['title'],100)}]({s['url']})" for i,s in enumerate(sources[:4],1))
    prompt = f'Question: {_clip(question,350)}\nEvidence synthesis: {_clip(synthesis,1400)}\nCritical analysis: {_clip(analysis,650)}\nVerifier: {_clip(verification,650)}\nSources:\n{source_list}'
    return llm('Write a concise Markdown research brief with title, executive summary, key findings, critical analysis, limitations, conclusion, and sources. Cite [S#]. Do not invent facts. Maximum 550 words.', prompt, 0.2, 650)
