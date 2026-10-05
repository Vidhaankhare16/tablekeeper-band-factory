import json, sys, time, urllib.request, os
from playwright.sync_api import sync_playwright, expect
BASE = os.environ.get('BASE', 'http://localhost:8099')
EV = '/tmp/e2e/ev3'
os.makedirs(EV, exist_ok=True)
COMBO = os.environ.get('COMBO') == '1'
def post(path, body):
    r = urllib.request.Request(BASE+path, json.dumps(body).encode(), {'Content-Type':'application/json'}, method='POST')
    return urllib.request.urlopen(r).status
def get(path):
    return json.load(urllib.request.urlopen(BASE+path))
rest = {"id":"r_anker","name":"Zum Anker","timezone":"Europe/Berlin","slot_minutes":30,"reservation_duration_minutes":90,
 "cancellation_cutoff_minutes":120,"opening_hours":[{"weekday":"thu","opens":"18:00","closes":"21:00"}],
 "tables":[{"id":"t_1","label":"1","capacity":2},{"id":"t_2","label":"Window 2","capacity":4},{"id":"t_3","label":"3","capacity":4}]}
if COMBO: rest["combinable"] = [["t_1","t_2"],["t_2","t_3"]]
FIX = {"users":[{"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada"}],"restaurants":[rest],"reservations":[{"id":"res_p","reference":"PAST01","user_id":"u_ada","restaurant_id":"r_anker","table_id":"t_1","party_size":2,"status":"confirmed","starts_at_local":"2020-01-02T19:00","starts_at":"2020-01-02T19:00:00+01:00","ends_at":"2020-01-02T20:30:00+01:00","created_at":"2019-12-01T10:00:00+00:00"}]}
DATE='2030-09-26'
results=[]
def check(name, cond):
    results.append((name, bool(cond))); print(('PASS ' if cond else 'FAIL ')+name, flush=True)

def tid(p,n): return p.get_by_test_id(n)
def login(p):
    p.goto(BASE+'/login'); tid(p,'login-email').fill('ada@example.com'); tid(p,'login-password').fill('correct horse'); tid(p,'login-submit').click()
    tid(p,'current-user').wait_for()
def search(p, party='2'):
    p.goto(BASE+'/')
    tid(p,'restaurant-select').select_option('r_anker'); tid(p,'date-input').fill(DATE); tid(p,'party-size-input').fill(party); tid(p,'search-button').click()
    tid(p,'availability-grid').wait_for()

def run(width, tag):
    post('/_test/reset', FIX)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get('CHROME','/opt/pw-browsers/chromium-1194/chrome-linux/chrome'))
        ctx = b.new_context(viewport={'width':width,'height':900}); p = ctx.new_page()
        def shot(n): p.screenshot(path=f'{EV}/{tag}-{n}.png', full_page=True)
        def noscroll(n): check(f'{tag} no horizontal scroll: {n}', p.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        # signed-out search + click
        search(p); shot('01-grid-signed-out'); noscroll('grid')
        c = tid(p,'slot-t_2-19:00'); check(f'{tag} cell available', c.get_attribute('data-available')=='true')
        check(f'{tag} small table unavailable for 4? (party 2 -> t_1 avail)', tid(p,'slot-t_1-19:00').get_attribute('data-available')=='true')
        c.click(); tid(p,'auth-error').wait_for(); shot('02-auth-required')
        # signup flow
        p.goto(BASE+'/signup'); tid(p,'signup-email').fill('ada@example.com'); tid(p,'signup-password').fill('longenough1'); tid(p,'signup-display-name').fill('Dup'); tid(p,'signup-submit').click()
        tid(p,'auth-error').wait_for(); shot('03-signup-error'); noscroll('signup')
        p.goto(BASE+'/login'); tid(p,'login-email').fill('ada@example.com'); tid(p,'login-password').fill('bad'); tid(p,'login-submit').click(); tid(p,'auth-error').wait_for()
        check(f'{tag} login wrong -> auth-error', True)
        login(p); check(f'{tag} current-user', 'Ada' in tid(p,'current-user').inner_text()); shot('04-login-ok')
        search(p,'4')
        check(f'{tag} t_1 too small for 4', tid(p,'slot-t_1-19:00').get_attribute('data-available')=='false')
        tid(p,'slot-t_1-19:00').click(); check(f'{tag} unavailable click does nothing', tid(p,'booking-form').count()==0)
        # booking
        tid(p,'slot-t_2-19:00').click(); tid(p,'booking-form').wait_for()
        check(f'{tag} summary', 'Window 2' in tid(p,'booking-summary').inner_text() and '19:00' in tid(p,'booking-summary').inner_text())
        check(f'{tag} party prefilled', tid(p,'booking-party-size').input_value()=='4'); shot('05-booking-form'); noscroll('booking')
        keys=[]; p.on('request', lambda r: keys.append((r.method, r.headers.get('idempotency-key'), r.post_data)) if r.url.endswith('/reservations') and r.method=='POST' else None)
        tid(p,'booking-submit').click(); tid(p,'confirmation').wait_for()
        ref = tid(p,'confirmation-reference').inner_text(); check(f'{tag} reference exact', len(ref)>=6 and ref.isalnum() and ref==ref.upper())
        check(f'{tag} details', 'Zum Anker' in tid(p,'confirmation-details').inner_text() and 'Window 2' in tid(p,'confirmation-details').inner_text())
        shot('06-confirmation'); noscroll('confirmation')
        tid(p,'booking-submit').click(); p.wait_for_timeout(600)
        check(f'{tag} resubmit same ref', tid(p,'confirmation-reference').inner_text()==ref and tid(p,'booking-error').count()==0)
        check(f'{tag} replay uses same key', len(keys)>=2 and keys[0][1]==keys[1][1] and keys[0][2]==keys[1][2])
        # 409: someone else took t_3
        post_other = lambda: None
        tid(p,'slot-t_3-19:30').click(); tid(p,'booking-form').wait_for()
        # grab token and take t_3 at 19:30 via other client
        tok = p.evaluate("JSON.parse(localStorage.getItem('tk.session')).token")
        def other(table, local, key, party=2):
            r = urllib.request.Request(BASE+'/reservations', json.dumps({'restaurant_id':'r_anker','table_id':table,'starts_at_local':local,'party_size':party}).encode(),
              {'Content-Type':'application/json','Authorization':'Bearer '+tok,'Idempotency-Key':key}, method='POST'); return urllib.request.urlopen(r).status
        other('t_3', DATE+'T19:30', 'other-1')
        tid(p,'booking-party-size').fill('3'); tid(p,'booking-submit').click(); tid(p,'booking-error').wait_for()
        check(f'{tag} 409 booking-error, form kept', tid(p,'booking-form').count()==1 and tid(p,'booking-party-size').input_value()=='3' and tid(p,'confirmation').count()==0)
        p.wait_for_timeout(500); check(f'{tag} 409 refreshed availability', tid(p,'slot-t_3-19:30').get_attribute('data-available')=='false'); shot('07-conflict')
        # lost response -> uncertain -> retry with same key
        tid(p,'slot-t_3-18:00').click(); keys.clear()
        state={'drop':True}
        def handler(route):
            if route.request.method=='POST' and state['drop']:
                route.fetch(); route.abort('connectionreset'); state['drop']=False
            else: route.continue_()
        p.route('**/reservations', handler)
        tid(p,'booking-submit').click(); tid(p,'booking-uncertain').wait_for()
        check(f'{tag} uncertain nonempty, no error/confirm', tid(p,'booking-uncertain').inner_text().strip()!='' and tid(p,'booking-error').count()==0 and tid(p,'confirmation').count()==0)
        shot('08-uncertain'); noscroll('uncertain')
        tid(p,'booking-submit').click(); tid(p,'confirmation').wait_for()
        check(f'{tag} retry same key+body', len(keys)==2 and keys[0][1]==keys[1][1] and keys[0][2]==keys[1][2])
        check(f'{tag} uncertainty removed', tid(p,'booking-uncertain').count()==0 and tid(p,'booking-error').count()==0)
        ref2 = tid(p,'confirmation-reference').inner_text()
        mine = get_with(tok)
        check(f'{tag} only one booking for lost response', sum(1 for x in mine if x['starts_at_local']==DATE+'T18:00')==1 and any(x['reference']==ref2 for x in mine))
        p.unroute('**/reservations')
        # out-of-order search
        search(p)
        delay={'n':0}
        def av(route):
            delay['n']+=1
            if delay['n']==1:
                time.sleep(1.2)
            route.continue_()
        # A (party 2) delayed, B (party 4) fast
        import threading
        p.route('**/availability*', lambda r: (r.fetch() and None) or None) if False else None
        sent=[]
        def avh(route):
            u=route.request.url
            if 'party_size=2' in u:
                resp=route.fetch(); p.wait_for_timeout(1500); route.fulfill(response=resp)
            else: route.continue_()
        p.route('**/availability*', avh)
        tid(p,'party-size-input').fill('2'); tid(p,'search-button').click()
        tid(p,'party-size-input').fill('4'); tid(p,'search-button').click()
        p.wait_for_timeout(2500)
        check(f'{tag} out-of-order: grid is B', tid(p,'slot-t_1-18:00').get_attribute('data-available')=='false')
        p.unroute('**/availability*')
        # lookup + cancel
        p.goto(BASE+'/lookup'); tid(p,'lookup-reference-input').fill(ref); tid(p,'lookup-submit').click(); tid(p,'reservation-detail').wait_for()
        check(f'{tag} lookup status', tid(p,'reservation-status').inner_text()=='confirmed' and 'Window 2' in tid(p,'reservation-tables').inner_text()); shot('09-lookup'); noscroll('lookup')
        tid(p,'reservation-cancel-button').click(); p.wait_for_function("document.querySelector('[data-testid=reservation-status]').textContent==='cancelled'")
        check(f'{tag} cancelled, button gone', tid(p,'reservation-cancel-button').count()==0); shot('10-cancelled')
        tid(p,'lookup-reference-input').fill('NOPE12'); tid(p,'lookup-submit').click(); tid(p,'reservation-error').wait_for(); check(f'{tag} not found error', tid(p,'reservation-detail').count()==0); shot('11-lookup-notfound')
        tid(p,'lookup-reference-input').fill('past01'); tid(p,'lookup-submit').click(); tid(p,'reservation-detail').wait_for(); tid(p,'reservation-cancel-button').click(); tid(p,'reservation-error').wait_for()
        check(f'{tag} cutoff refused, still confirmed', tid(p,'reservation-status').inner_text()=='confirmed' and tid(p,'reservation-cancel-button').count()==1); shot('11b-cancel-refused')
        # logout
        tid(p,'logout-button').click(); check(f'{tag} logout', tid(p,'current-user').count()==0)
        # no-slots
        search(p) if False else None
        p.goto(BASE+'/'); tid(p,'restaurant-select').select_option('r_anker'); tid(p,'date-input').fill('2030-09-27'); tid(p,'search-button').click(); tid(p,'no-slots').wait_for(); shot('12-no-slots'); noscroll('no-slots')
        b.close()

def get_with(tok):
    r = urllib.request.Request(BASE+'/reservations', headers={'Authorization':'Bearer '+tok}); return json.load(urllib.request.urlopen(r))['reservations']

for w,t in ((375,'m375'),(1280,'d1280')): run(w,t)
bad=[n for n,ok in results if not ok]; print(f'\n{len(results)-len(bad)}/{len(results)} passed'); sys.exit(1 if bad else 0)
