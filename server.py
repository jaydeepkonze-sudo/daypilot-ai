#!/usr/bin/env python3
"""DayPilot AI: zero-dependency local demo + JSON-RPC MCP Streamable HTTP server.
MCP endpoint is intentionally stateless and request/response over Streamable HTTP.
"""
import json, os, re, sqlite3, threading, uuid
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('DAYPILOT_DB',str(ROOT/'daypilot.db')))
LOCK=threading.RLock()
PORT=int(os.environ.get('PORT','8765'))

def connection():
    c=sqlite3.connect(str(DB), timeout=15)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connection() as c:
        c.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL, priority TEXT NOT NULL, minutes INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)')
        c.commit()

def tasks():
    with LOCK,connection() as c:
        return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY done ASC, CASE priority WHEN "high" THEN 0 WHEN "medium" THEN 1 ELSE 2 END, created_at ASC').fetchall()]

def add_task(title,priority='medium',minutes=30):
    title=re.sub(r'\s+',' ',str(title)).strip()[:140]
    if not title: raise ValueError('Task title cannot be empty')
    priority=str(priority).lower()
    if priority not in ('high','medium','low'): priority='medium'
    try: minutes=int(minutes)
    except (TypeError, ValueError): minutes=30
    minutes=max(5,min(240,minutes))
    record={'id':uuid.uuid4().hex[:12], 'title':title,'priority':priority,'minutes':minutes,'done':0,'created_at':datetime.now().isoformat(timespec='seconds')}
    with LOCK,connection() as c:
        c.execute('INSERT INTO tasks VALUES (:id,:title,:priority,:minutes,:done,:created_at)',record)
        c.commit()
    return record

def update_task(id,done=None,delete=False):
    with LOCK,connection() as c:
        if not c.execute('SELECT id FROM tasks WHERE id=?',(id,)).fetchone():raise ValueError('Task not found')
        if delete:c.execute('DELETE FROM tasks WHERE id=?',(id,))
        else:c.execute('UPDATE tasks SET done=? WHERE id=?',(int(bool(done)),id))
        c.commit()
    return True

def plan(start='09:00'):
    """Calculate all schedule timestamps in Python (never ask an LLM to do time arithmetic)."""
    try:
        clock = datetime.strptime(start, '%H:%M')
    except (ValueError, TypeError):
        clock = datetime.strptime('09:00', '%H:%M')
    actual_start = clock.strftime('%H:%M')
    pending = [t for t in tasks() if not t['done']]
    items = []
    for n, task in enumerate(pending):
        if n and n % 3 == 0:
            ending = clock + timedelta(minutes=15)
            items.append({'time': clock.strftime('%I:%M %p'),
                          'end_time': ending.strftime('%I:%M %p'),
                          'title': 'Recharge break', 'minutes': 15, 'kind': 'break'})
            clock = ending
        ending = clock + timedelta(minutes=task['minutes'])
        items.append({'time': clock.strftime('%I:%M %p'),
                      'end_time': ending.strftime('%I:%M %p'),
                      'title': task['title'], 'minutes': task['minutes'],
                      'kind': task['priority'], 'id': task['id']})
        clock = ending
    return {'items': items, 'total_minutes': sum(t['minutes'] for t in pending),
            'pending': len(pending),
            'message': f'Your plan has {len(pending)} focus blocks, starting at {actual_start}.' if pending
                       else 'Your schedule is clear. Add a task to build a plan.'}


def format_plan_reply(schedule):
    """Authoritative plan text: only use validated timestamps returned by plan()."""
    if not schedule['pending']:
        return 'You have no pending tasks. Add a task and I can plan your day.'
    lines = ['Here is your prioritized daily plan:']
    for item in schedule['items']:
        tag = ' (break)' if item['kind'] == 'break' else f" ({item['kind']} priority)"
        lines.append(f"{item['time']} - {item['end_time']}: {item['title']}{tag} — {item['minutes']} minutes")
    lines.append('High-priority tasks come first. Times are calculated from saved task durations.')
    return '\n'.join(lines)


def requested_plan_start(message):
    """Extract optional explicit start times from planning requests."""
    match = re.search(r'\b(?:at|from|starting at|start at)\s+(\d{1,2}):(\d{2})\s*(am|pm)?\b', message, re.I)
    if not match:
        return '09:00'
    hour, minute = int(match.group(1)), int(match.group(2))
    period = (match.group(3) or '').lower()
    if period:
        if not 1 <= hour <= 12 or minute > 59:
            return '09:00'
        hour = hour % 12 + (12 if period == 'pm' else 0)
    if hour > 23 or minute > 59:
        return '09:00'
    return f'{hour:02d}:{minute:02d}'


def overview():
    all_t=tasks();pending=[x for x in all_t if not x['done']]
    return {'total':len(all_t),'completed':len(all_t)-len(pending),'pending':len(pending),'high_priority':sum(t['priority']=='high' for t in pending),'focus_minutes':sum(t['minutes'] for t in pending)}

TOOLS=[
 {'name':'add_task','description':'Add a task to the DayPilot productivity planner, including priority and expected duration.','inputSchema':{'type':'object','properties':{'title':{'type':'string','description':'Short task name'},'priority':{'type':'string','enum':['high','medium','low']},'minutes':{'type':'integer','minimum':5,'maximum':240}},'required':['title']}},
 {'name':'list_tasks','description':'List tasks and their status, priority, and estimated duration.','inputSchema':{'type':'object','properties':{}}},
 {'name':'complete_task','description':'Mark a task completed by its id.','inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id']}},
 {'name':'delete_task','description':'Delete a task by its id.','inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id']}},
 {'name':'plan_day','description':'Build a realistic, prioritized daily schedule with focus blocks and breaks.','inputSchema':{'type':'object','properties':{'start':{'type':'string','description':'24-hour start time HH:MM'}}}},
 {'name':'get_progress','description':'Get a productivity summary with completion and outstanding focus minutes.','inputSchema':{'type':'object','properties':{}}}
]
def tool_call(name,args):
    args=args or {}
    if name=='add_task':return {'task':add_task(args.get('title',''),args.get('priority','medium'),args.get('minutes',30))}
    if name=='list_tasks':return {'tasks':tasks()}
    if name=='complete_task':update_task(str(args.get('id','')),True);return {'success':True,'tasks':tasks()}
    if name=='delete_task':update_task(str(args.get('id','')),delete=True);return {'success':True,'tasks':tasks()}
    if name=='plan_day':return plan(args.get('start','09:00'))
    if name=='get_progress':return overview()
    raise ValueError(f'Unknown tool: {name}')

def interpret(prompt):
    """Deterministic local intent simulation, not a generative model or Alexa+ connection."""
    q=re.sub(r'\s+',' ',str(prompt)).strip()
    low=q.lower()
    if not q:return {'reply':'Tell me what you would like to do. I can add a task, plan your day, or track progress.','intent':'help'}
    if re.search(r'\b(help|what can you do|commands)\b',low):
        return {'reply':'Try “Add finish proposal high priority for 45 minutes”, “Plan my day”, “Show my tasks”, or “What should I focus on?”','intent':'help'}
    if re.search(r'\b(add|create|remind me to|i need to|remember to)\b',low):
        title=re.sub(r'^(hey daypilot[, ]*|please |can you |could you )','',q,flags=re.I)
        title=re.sub(r'^(add|create)( an? )?(task( to)? )?|remind me to |i need to |remember to ','',title,flags=re.I)
        priority='high' if re.search(r'\b(high|urgent|important)\b',low) else ('low' if re.search(r'\blow\b',low) else 'medium')
        m=re.search(r'(\d+)\s*(minutes?|mins?|hours?|hrs?)',low)
        duration=(int(m.group(1))*60 if m and m.group(2).startswith(('hour','hr')) else int(m.group(1))) if m else 30
        title=re.sub(r'\b(high|medium|low)\s*(priority)?\b','',title,flags=re.I)
        title=re.sub(r'\b(for|in)\s+\d+\s*(minutes?|mins?|hours?|hrs?)\b','',title,flags=re.I).strip(' .,-')
        if not title:return {'reply':'What task should I add? Try “Add prepare slides high priority for 40 minutes”.','intent':'help'}
        t=add_task(title,priority,duration)
        return {'reply':f'Added “{t["title"]}” as {priority} priority, estimated {t["minutes"]} minutes. Your plan is updated.','intent':'add_task','data':t}
    if re.search(r'\b(plan|schedule|organize|organise)\b',low):
        p=plan(requested_plan_start(q)); return {'reply':format_plan_reply(p),'intent':'plan_day','data':p}
    if re.search(r'\b(focus|next|most important|priorit)\b',low):
        pending=[t for t in tasks() if not t['done']]
        if not pending:return {'reply':'You are all caught up. Add a new task to start planning.','intent':'focus'}
        t=pending[0]
        return {'reply':f'Start with “{t["title"]}”. It is {t["priority"]} priority and needs about {t["minutes"]} minutes. I recommend one distraction-free focus block.','intent':'focus','data':t}
    if re.search(r'\b(show|list|what are|my tasks|pending tasks)\b',low):
        pending=[t for t in tasks() if not t['done']]
        return {'reply':('Your next tasks: '+ '; '.join(t['title'] for t in pending[:5])+'.') if pending else 'You have no pending tasks.','intent':'list_tasks','data':pending}
    if re.search(r'\b(progress|doing|summary|completed|productive)\b',low):
        o=overview()
        return {'reply':f'You have completed {o["completed"]} of {o["total"]} tasks. {o["pending"]} remain, totaling {o["focus_minutes"]} minutes of estimated work.','intent':'get_progress','data':o}
    return {'reply':'I can help you organize work. Try “Add prepare my presentation high priority”, “Plan my day”, or “What should I focus on?”. For open-ended AI questions, a generative model is not connected in this offline demo.','intent':'fallback'}

# Optional, real local LLM. No API key, cloud subscription, or model bundled.
OLLAMA_URL=os.environ.get('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL=os.environ.get('OLLAMA_MODEL','qwen2.5:3b')

def ollama_request(path,payload=None,timeout=8):
    url=OLLAMA_URL+path
    if payload is None: req=Request(url)
    else: req=Request(url,data=json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=timeout) as res:return json.load(res)

def ai_status():
    try:
        data=ollama_request('/api/tags',timeout=2)
        names=[x.get('name','') for x in data.get('models',[])]
        model=OLLAMA_MODEL
        # Ollama may tag as :latest
        available=model in names or (':' not in model and model+':latest' in names)
        return {'connected':True,'ready':available,'model':model,'installed_models':names}
    except (OSError,ValueError,TimeoutError):return {'connected':False,'ready':False,'model':OLLAMA_MODEL,'installed_models':[]}

SYSTEM_PROMPT="""You are DayPilot, a thoughtful and helpful productivity assistant. You run locally on the user's computer. Provide clear, short, natural answers, never invent completed actions. You can use the provided tools to inspect and modify the actual user's task list, plan their day, and report progress. When a user asks to add, complete or delete a task, call the appropriate tool rather than claiming you did it. Never invent or calculate timestamps in natural language. Use plan_day tool returned times as authoritative. For complete/delete, first retrieve the task list to find its exact ID. Ask for clarification if ambiguous. Never pretend you are officially integrated with Amazon Alexa+. Speak in the user's language when practical."""

def ai_chat(message,history=None):
    if not isinstance(message,str) or not message.strip():raise ValueError('Message is empty')
    if len(message)>4000:raise ValueError('Message is too long')
    status=ai_status()
    if not status['ready']:
        explanation=('Ollama is not running.' if not status['connected'] else 'The model '+OLLAMA_MODEL+' is not installed.')
        return {'reply':explanation+' Install Ollama from ollama.com, run "ollama pull '+OLLAMA_MODEL+'", then restart or refresh DayPilot. Meanwhile basic task commands still work in Offline mode.','intent':'ai_unavailable','mode':'unavailable'}
    # Scheduling arithmetic must never be produced by the language model.
    # Route explicit daily-plan requests through the trusted planner. Other
    # questions and task-management requests still use Ollama tool-calling.
    if re.search(r'\b(plan my day|plan today|daily plan|today.s plan|plan for today|schedule (?:my|for|today)|reorganize my day|reorganise my day|realistic plan|create a plan|make a plan|build a plan)\b', message, re.I):
        schedule = plan(requested_plan_start(message))
        return {'reply': format_plan_reply(schedule), 'intent': 'plan_day',
                'mode': 'verified_plan', 'data': schedule}
    messages=[{'role':'system','content':SYSTEM_PROMPT}]
    for h in (history if isinstance(history,list) else [])[-10:]:
        if isinstance(h,dict) and h.get('role') in ('user','assistant') and isinstance(h.get('content'),str):
            messages.append({'role':h['role'],'content':h['content'][:1500]})
    messages.append({'role':'user','content':message})
    # Tool-calling via Ollama's local /api/chat; bounded to avoid infinite loops.
    for iteration in range(5):
        try:
            result=ollama_request('/api/chat',{'model':OLLAMA_MODEL,'messages':messages,'tools':[{'type':'function','function':{'name':t['name'],'description':t['description'],'parameters':t['inputSchema']}} for t in TOOLS],'stream':False,'options':{'temperature':0.35}},timeout=120)
        except (OSError,ValueError,TimeoutError) as exc:
            return {'reply':'Local AI request failed: '+str(exc)+'. Check that Ollama is running and the model is installed.','intent':'ai_error','mode':'error'}
        response=result.get('message') or {};calls=response.get('tool_calls') or []
        messages.append(response)
        if not calls:
            return {'reply':response.get('content','').strip() or 'I could not generate a response. Please try again.','intent':'ai','mode':'local_ai'}
        for call in calls[:5]:
            fn=call.get('function') or {};name=fn.get('name');args=fn.get('arguments') or {}
            if isinstance(args,str):
                try:args=json.loads(args)
                except ValueError:args={}
            try: output=tool_call(name,args)
            except (ValueError,TypeError) as e:output={'error':str(e)}
            messages.append({'role':'tool','content':json.dumps(output,ensure_ascii=False)})
    return {'reply':'I reached the tool-action limit. Check your task list for completed actions, then ask another question.','intent':'ai_limit','mode':'local_ai'}

class Handler(BaseHTTPRequestHandler):
    server_version='DayPilot/2.0'
    def log_message(self,fmt,*args):pass
    def send(self,code,data=None,ctype='application/json',headers=None):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type',ctype+'; charset=utf-8');self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','Content-Type, MCP-Protocol-Version, MCP-Session-Id, Authorization');self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        if headers:
            for k,v in headers.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def do_OPTIONS(self):self.send(204,b'')
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/state':return self.send(200,{'tasks':tasks(),'overview':overview(),'plan':plan()})
        if path=='/api/ai/status':return self.send(200,ai_status())
        if path=='/health':return self.send(200,{'ok':True,'service':'daypilot','mcp':'2025-11-25'})
        if path=='/mcp':return self.send(405,{'error':'Use Streamable HTTP POST with JSON-RPC messages'})
        if path in ('/','/index.html'):path='/static/index.html'
        if path.startswith('/static/'):
            name=path[len('/static/'):]
            if name not in ('index.html','app.js','style.css'):return self.send(404,{'error':'not found'})
            data=(ROOT/'static'/name).read_bytes()
            ctype={'index.html':'text/html','app.js':'text/javascript','style.css':'text/css'}[name]
            return self.send(200,data,ctype)
        self.send(404,{'error':'not found'})
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>1024*1024:return self.send(413,{'error':'body too large'})
            data=json.loads(self.rfile.read(length))
            path=urlparse(self.path).path
            if path=='/mcp':return self.handle_mcp(data)
            if path=='/api/ask':return self.send(200,interpret(data.get('message','')))
            if path=='/api/ai/chat':return self.send(200,ai_chat(data.get('message',''),data.get('history',[])))
            if path=='/api/task':return self.send(200,{'task':add_task(data.get('title',''),data.get('priority','medium'),data.get('minutes',30))})
            if path=='/api/complete':return self.send(200,{'success':update_task(str(data.get('id','')),bool(data.get('done',True)))})
            if path=='/api/delete':return self.send(200,{'success':update_task(str(data.get('id','')),delete=True)})
            if path=='/api/demo':
                if not tasks():
                    for title,priority,minutes in [('Prepare hackathon pitch','high',50),('Build Alexa+ MCP demo','high',90),('Record demo walkthrough','medium',40),('Review submission checklist','medium',20),('Plan tomorrow’s priorities','low',15)]:add_task(title,priority,minutes)
                return self.send(200,{'tasks':tasks()})
            self.send(404,{'error':'not found'})
        except (ValueError,KeyError,TypeError) as e:self.send(400,{'error':str(e)})
        except Exception as e:self.send(500,{'error':'Internal server error'})
    def handle_mcp(self,d):
        if not isinstance(d,dict):return self.send(400,{'error':'JSON-RPC object expected'})
        method=d.get('method','');id=d.get('id');args=d.get('params') or {}
        if id is None:return self.send(202,b'')
        try:
            if method=='initialize':result={'protocolVersion':'2025-11-25','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'daypilot-ai','version':'2.0.0'},'instructions':'Manage personal tasks, priorities, and daily planning with DayPilot tools.'}
            elif method=='ping':result={}
            elif method=='tools/list':result={'tools':TOOLS}
            elif method=='tools/call':
                output=tool_call(args.get('name',''),args.get('arguments') or {})
                result={'content':[{'type':'text','text':json.dumps(output)}],'structuredContent':output,'isError':False}
            else:return self.send(200,{'jsonrpc':'2.0','id':id,'error':{'code':-32601,'message':'Method not found'}})
            return self.send(200,{'jsonrpc':'2.0','id':id,'result':result},headers={'MCP-Protocol-Version':'2025-11-25'})
        except (ValueError,TypeError) as e:
            return self.send(200,{'jsonrpc':'2.0','id':id,'result':{'content':[{'type':'text','text':str(e)}],'isError':True}})

if __name__=='__main__':
    init_db();print(f'\n DayPilot AI is running: http://localhost:{PORT}\n MCP endpoint: http://localhost:{PORT}/mcp\n Press Ctrl+C to stop.\n',flush=True)
    ThreadingHTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
