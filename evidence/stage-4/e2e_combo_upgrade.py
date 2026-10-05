import json, os, sys, urllib.request
sys.argv=['x']; os.environ['COMBO']='1'
src=open('/tmp/e2e/e2e.py').read().split("for w,t in ((375")[0]
exec(src)
def export(): return json.load(urllib.request.urlopen(BASE+'/_test/export'))
def imp(o): return post('/_test/import', o)
def runc(width, tag):
    global DATE
    DATE='2030-09-26'
    post('/_test/reset', FIX)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome'); p = b.new_context(viewport={'width':width,'height':900}).new_page()
        def shot(n): p.screenshot(path=f'{EV}/{tag}-{n}.png', full_page=True)
        def noscroll(n): check(f'{tag} no hscroll {n}', p.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
        login(p); search(p,'6'); shot('20-combo-grid'); noscroll('combo grid')
        check(f'{tag} combo cell exists+true', tid(p,'slot-t_1+t_2-19:30').get_attribute('data-available')=='true')
        check(f'{tag} reverse-pair cell absent', tid(p,'slot-t_2+t_1-19:30').count()==0)
        check(f'{tag} single too small false', tid(p,'slot-t_2-19:30').get_attribute('data-available')=='false')
        tid(p,'slot-t_1+t_2-19:30').click(); tid(p,'booking-form').wait_for()
        s=tid(p,'booking-summary').inner_text(); check(f'{tag} summary names both', '1' in s and 'Window 2' in s and '19:30' in s); shot('21-combo-form')
        keys=[]; p.on('request', lambda r: keys.append((r.headers.get('idempotency-key'), r.post_data)) if r.url.endswith('/reservations') and r.method=='POST' else None)
        tid(p,'booking-submit').click(); tid(p,'confirmation').wait_for()
        ct=tid(p,'confirmation-tables').inner_text(); check(f'{tag} confirmation-tables both', '1' in ct and 'Window 2' in ct); shot('22-combo-confirmed')
        ref=tid(p,'confirmation-reference').inner_text()
        p.wait_for_timeout(500)
        check(f'{tag} after booking pair+members unavailable', all(tid(p,f'slot-{x}-19:30').get_attribute('data-available')=='false' for x in ('t_1+t_2','t_2+t_3','t_2')) )
        p.goto(BASE+'/lookup'); tid(p,'lookup-reference-input').fill(ref); tid(p,'lookup-submit').click(); tid(p,'reservation-detail').wait_for()
        rt=tid(p,'reservation-tables').inner_text(); check(f'{tag} lookup tables both', '1' in rt and 'Window 2' in rt)
        # lost response on combo + export/import upgrade + retry
        search(p,'6'); tid(p,'slot-t_1+t_2-18:00').click(); tid(p,'booking-form').wait_for(); keys.clear()
        st={'drop':True}
        def h(route):
            if route.request.method=='POST' and st['drop']: route.fetch(); route.abort('connectionreset'); st['drop']=False
            else: route.continue_()
        p.route('**/reservations', h)
        tid(p,'booking-submit').click(); tid(p,'booking-uncertain').wait_for(); shot('23-combo-uncertain')
        exp=export(); imp(exp)   # server upgrade between requests
        tid(p,'booking-submit').click(); tid(p,'confirmation').wait_for()
        r2=tid(p,'confirmation-reference').inner_text()
        check(f'{tag} retry after import: same key/body', len(keys)==2 and keys[0]==keys[1])
        check(f'{tag} retry after import: still signed in, no error', tid(p,'current-user').count()==1 and tid(p,'booking-error').count()==0 and tid(p,'booking-uncertain').count()==0)
        tok=p.evaluate("JSON.parse(localStorage.getItem('tk.session')).token")
        rq=urllib.request.Request(BASE+'/reservations',headers={'Authorization':'Bearer '+tok}); mine=json.load(urllib.request.urlopen(rq))['reservations']
        check(f'{tag} single combo booking at 18:00 with original ref', [x['reference'] for x in mine if x['starts_at_local'].endswith('18:00')]==[r2])
        # 409 on combo

        DATE='2030-10-03'
        search(p,'6'); tid(p,'slot-t_2+t_3-19:00').click() if False else None
        tid(p,'slot-t_2+t_3-19:30').click(); tid(p,'booking-form').wait_for()
        rq=urllib.request.Request(BASE+'/reservations', json.dumps({'restaurant_id':'r_anker','table_id':'t_3','starts_at_local':'2030-10-03T19:30','party_size':2}).encode(), {'Content-Type':'application/json','Authorization':'Bearer '+tok,'Idempotency-Key':'x1'}, method='POST'); urllib.request.urlopen(rq)
        tid(p,'booking-submit').click(); tid(p,'booking-error').wait_for(); p.wait_for_timeout(500)
        check(f'{tag} combo 409 error, no confirmation, form kept, refreshed', tid(p,'confirmation').count()==0 and tid(p,'booking-form').count()==1 and tid(p,'slot-t_2+t_3-19:30').get_attribute('data-available')=='false'); shot('24-combo-conflict')
        b.close()
for w,t in ((375,'m375'),(1280,'d1280')): runc(w,t)
bad=[n for n,ok in results if not ok]; print(f'\n{len(results)-len(bad)}/{len(results)} passed'); sys.exit(1 if bad else 0)
