import json, queue, threading, time
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, EmailStr
from typing import Literal
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from .config import FRONTEND_ORIGIN, GROQ_MODEL
from .database import init_db, SessionLocal, ResearchRun, User, Workspace
from .auth import get_current_user, hash_password, verify_password, create_token
from .agents import plan_research, search_web, synthesize, analyze, verify, write_report, score_sources, AgentError

@asynccontextmanager
async def lifespan(app: FastAPI):
    try: init_db(); app.state.db_available=True; app.state.db_error=None
    except Exception as exc: app.state.db_available=False; app.state.db_error=str(exc)
    yield

app = FastAPI(title='ResearchPilot AI API', description='Authenticated multi-agent research, evidence review, and report workspace.', version='1.0.0', lifespan=lifespan)
origins = list(dict.fromkeys([FRONTEND_ORIGIN, 'http://localhost:5173', 'http://127.0.0.1:5173']))
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
class WorkspaceRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
class ResearchRequest(BaseModel):
    question: str = Field(min_length=8, max_length=1000)
    depth: Literal['quick','standard','deep'] = 'standard'
    workspace_id: str | None = None
class NotesRequest(BaseModel):
    notes: str = Field(max_length=5000)

@app.get('/api/health')
def health():
    return {'status':'ok', 'database':'connected' if getattr(app.state,'db_available',False) else 'unavailable',
            'database_note':getattr(app.state,'db_error',None), 'model':GROQ_MODEL, 'auth':'enabled'}

@app.post('/api/auth/register')
def register(payload: RegisterRequest):
    with SessionLocal() as db:
        email = payload.email.lower().strip()
        if db.query(User).filter(User.email == email).first(): raise HTTPException(status_code=409, detail='An account with this email already exists.')
        user = User(id=str(uuid4()), name=payload.name.strip(), email=email, password_hash=hash_password(payload.password))
        db.add(user)
        try: db.flush()
        except IntegrityError: db.rollback(); raise HTTPException(status_code=409, detail='An account with this email already exists.')
        workspace = Workspace(id=str(uuid4()), owner_id=user.id, name='My research')
        db.add(workspace); db.commit(); db.refresh(user); db.refresh(workspace)
        token = create_token(user)
        return {'token':token, 'user':{'id':user.id,'name':user.name,'email':user.email}, 'workspace':workspace_dict(workspace)}

@app.post('/api/auth/login')
def login(payload: LoginRequest):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
        if not user or not verify_password(payload.password, user.password_hash): raise HTTPException(status_code=401, detail='Email or password is incorrect.')
        return {'token':create_token(user), 'user':{'id':user.id,'name':user.name,'email':user.email}}

@app.get('/api/auth/me')
def me(user: User = Depends(get_current_user)):
    return {'id':user.id,'name':user.name,'email':user.email}

def workspace_dict(w):
    return {'id':w.id,'name':w.name,'created_at':w.created_at.isoformat() if w.created_at else None}

@app.get('/api/workspaces')
def list_workspaces(user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        rows=db.query(Workspace).filter(Workspace.owner_id==user.id).order_by(Workspace.created_at.asc()).all()
        return [workspace_dict(w) for w in rows]

@app.post('/api/workspaces')
def create_workspace(payload: WorkspaceRequest, user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        w=Workspace(id=str(uuid4()),owner_id=user.id,name=payload.name.strip())
        db.add(w); db.commit(); db.refresh(w)
        return workspace_dict(w)

@app.delete('/api/workspaces/{workspace_id}')
def delete_workspace(workspace_id: str, user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        w=db.query(Workspace).filter(Workspace.id==workspace_id,Workspace.owner_id==user.id).first()
        if not w: raise HTTPException(status_code=404,detail='Workspace not found.')
        # Keep research history; move its runs into the user's general workspace (NULL workspace).
        db.query(ResearchRun).filter(ResearchRun.workspace_id==w.id,ResearchRun.user_id==user.id).update({ResearchRun.workspace_id:None})
        db.delete(w); db.commit()
        return {'deleted':True}

def verify_workspace(db, workspace_id, user_id):
    if not workspace_id: return None
    workspace=db.query(Workspace).filter(Workspace.id==workspace_id,Workspace.owner_id==user_id).first()
    if not workspace: raise HTTPException(status_code=404,detail='Selected workspace was not found.')
    return workspace.id

def get_memory(user_id: str, question: str) -> str:
    # Lightweight memory: previous related question/report excerpts, never entire prior reports.
    try:
        with SessionLocal() as db:
            rows=db.query(ResearchRun).filter(ResearchRun.user_id==user_id,ResearchRun.status=='completed').order_by(ResearchRun.created_at.desc()).limit(3).all()
            if not rows: return ''
            return '\n'.join(f"Previous investigation: {r.question[:120]} | conclusion context: {r.report[-180:].replace(chr(10),' ')}" for r in rows)
    except Exception: return ''

def execute_pipeline(payload: ResearchRequest, user: User, emit=None):
    start=time.perf_counter(); run_id=str(uuid4()); events=[]; warnings=[]
    def stage(agent, detail, status='completed'):
        event={'agent':agent,'status':status,'detail':detail,'elapsed_ms':round((time.perf_counter()-start)*1000)}
        events.append(event)
        if emit: emit({'type':'progress','event':event})
    try:
        stage('Planner','Creating a focused research plan.','running')
        plan=plan_research(payload.question,payload.depth,get_memory(user.id,payload.question))
        stage('Planner',f'Created {len(plan)} targeted search queries.')
        stage('Search Agent','Searching public web snippets.','running')
        sources=search_web(plan)
        stage('Search Agent',f'Retrieved {len(sources)} unique sources.' if sources else 'No web results returned; report will be limited.', 'completed' if sources else 'warning')
        if not sources: warnings.append('No web results were retrieved. Check internet access or try broader search terms.')
        stage('Research Agent','Synthesizing evidence snippets.','running')
        synthesis=synthesize(payload.question,plan,sources)
        stage('Research Agent','Evidence synthesis completed.')
        stage('Analyst Agent','Identifying patterns, trade-offs, and gaps.','running')
        analysis=analyze(payload.question,synthesis)
        stage('Analyst Agent','Critical analysis completed.')
        stage('Verifier Agent','Reviewing claims against the retrieved snippets.','running')
        verification=verify(payload.question,synthesis,analysis,sources)
        stage('Verifier Agent','Claim review completed; verification is heuristic, not a guarantee.')
        stage('Writer Agent','Writing the structured research brief.','running')
        report=write_report(payload.question,synthesis,analysis,verification,sources)
        stage('Writer Agent','Report generated.')
        metrics=score_sources(sources)
        metrics.update({'duration_ms':round((time.perf_counter()-start)*1000),'agent_count':6,'depth':payload.depth,'plan_count':len(plan)})
        with SessionLocal() as db:
            workspace_id=verify_workspace(db,payload.workspace_id,user.id)
            row=ResearchRun(id=run_id,user_id=user.id,workspace_id=workspace_id,question=payload.question.strip(),depth=payload.depth,status='completed',report=report,
                plan_json=json.dumps(plan),sources_json=json.dumps(sources),events_json=json.dumps(events),analysis=analysis,verification=verification,metrics_json=json.dumps(metrics))
            db.add(row); db.commit()
        result={'run_id':run_id,'question':payload.question,'depth':payload.depth,'workspace_id':payload.workspace_id,'plan':plan,'sources':sources,'analysis':analysis,'verification':verification,'report':report,'events':events,'warnings':warnings,'metrics':metrics}
        if emit: emit({'type':'result','result':result})
        return result
    except Exception as exc:
        stage('Orchestrator',str(exc)[:260],'error')
        if isinstance(exc, HTTPException): raise
        if isinstance(exc, AgentError): raise HTTPException(status_code=429 if 'token limit' in str(exc).lower() else 502, detail=str(exc)) from exc
        if isinstance(exc, SQLAlchemyError): raise HTTPException(status_code=503,detail='Database operation failed. Check PostgreSQL status and DATABASE_URL.') from exc
        raise HTTPException(status_code=500,detail=f'Research failed: {str(exc)[:400]}') from exc

@app.post('/api/research')
def run_research(payload: ResearchRequest, user: User = Depends(get_current_user)):
    return execute_pipeline(payload,user)

@app.post('/api/research/stream')
def run_research_stream(payload: ResearchRequest, user: User = Depends(get_current_user)):
    # Server-sent event stream; the worker emits real pipeline progress as each stage finishes.
    messages=queue.Queue(); sentinel=object()
    def emit(item): messages.put(item)
    def worker():
        try: execute_pipeline(payload,user,emit)
        except HTTPException as exc: emit({'type':'error','detail':exc.detail,'status_code':exc.status_code})
        except Exception as exc: emit({'type':'error','detail':str(exc)[:300],'status_code':500})
        finally: messages.put(sentinel)
    threading.Thread(target=worker,daemon=True).start()
    def stream():
        while True:
            item=messages.get()
            if item is sentinel: break
            yield 'data: '+json.dumps(item,ensure_ascii=False)+'\n\n'
        yield 'event: done\ndata: {}\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

def serialize_run(row):
    def load(value, fallback):
        try: return json.loads(value or '')
        except Exception: return fallback
    return {'id':row.id,'run_id':row.id,'question':row.question,'depth':row.depth,'workspace_id':row.workspace_id,'status':row.status,'report':row.report,
        'plan':load(row.plan_json,[]),'sources':load(row.sources_json,[]),'events':load(row.events_json,[]),'analysis':row.analysis,'verification':row.verification,
        'notes':row.notes,'metrics':load(row.metrics_json,{}),'created_at':row.created_at.isoformat() if row.created_at else None}

@app.get('/api/research/history')
def research_history(limit: int=Query(50,ge=1,le=100), q: str | None=None, workspace_id: str | None=None, user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        query=db.query(ResearchRun).filter(ResearchRun.user_id==user.id)
        if q and q.strip(): query=query.filter(ResearchRun.question.ilike(f'%{q.strip()[:100]}%'))
        if workspace_id == 'none': query=query.filter(ResearchRun.workspace_id.is_(None))
        elif workspace_id: query=query.filter(ResearchRun.workspace_id==workspace_id)
        rows=query.order_by(ResearchRun.created_at.desc()).limit(limit).all()
        return [serialize_run(row) for row in rows]

@app.get('/api/research/{run_id}')
def research_detail(run_id: str, user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        row=db.query(ResearchRun).filter(ResearchRun.id==run_id,ResearchRun.user_id==user.id).first()
        if not row: raise HTTPException(status_code=404,detail='Research report not found.')
        return serialize_run(row)

@app.patch('/api/research/{run_id}/notes')
def update_notes(run_id: str, payload: NotesRequest, user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        row=db.query(ResearchRun).filter(ResearchRun.id==run_id,ResearchRun.user_id==user.id).first()
        if not row: raise HTTPException(status_code=404,detail='Research report not found.')
        row.notes=payload.notes; db.commit()
        return {'saved':True,'notes':row.notes}

@app.delete('/api/research/{run_id}')
def delete_research(run_id: str, user: User = Depends(get_current_user)):
    with SessionLocal() as db:
        row=db.query(ResearchRun).filter(ResearchRun.id==run_id,ResearchRun.user_id==user.id).first()
        if not row: raise HTTPException(status_code=404,detail='Research report not found.')
        db.delete(row); db.commit()
        return {'deleted':True}
