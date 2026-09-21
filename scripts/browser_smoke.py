"""Run after npm run build. Uses synthetic data, a local Flask server and Chromium."""
import os,sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from config import Config
from backend.api import create_app
from backend.bridge import Bridge
from playwright.sync_api import sync_playwright

with tempfile.TemporaryDirectory() as directory:
    cfg=Config(token='123:test-placeholder',admin_id=99,data_dir=Path(directory),keys=(Fernet.generate_key().decode(),),
               payment_mode='stars',support='',origin='http://127.0.0.1:5011',secret_key='s'*48,
               password_hash=generate_password_hash('test-dashboard-password'))
    bridge=Bridge(cfg);server=make_server('127.0.0.1',5011,create_app(cfg,bridge),threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.getenv("CHROMIUM_EXECUTABLE") or None, args=["--no-sandbox"])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(cfg.origin)
            page.get_by_label('Dashboard password').fill('test-dashboard-password')
            page.get_by_role('button',name='Open workspace').click()
            page.get_by_role('heading',name='Your research, at a glance.').wait_for()
            page.get_by_role('button',name='Services',exact=True).click()
            page.get_by_role('button',name='New service').click()
            page.get_by_label('Name',exact=True).fill('Browser test service')
            page.get_by_label('Description',exact=True).fill('Synthetic browser test data')
            page.get_by_label('Telegram Stars price').fill('100')
            page.get_by_role('button',name='Save service').click()
            card=page.get_by_role('article').filter(has=page.get_by_role('heading',name='Browser test service'))
            card.get_by_role('button',name='Open content').click()
            page.get_by_role('button',name='Add reference').click()
            page.get_by_label('Title',exact=True).fill('Browser draft')
            page.get_by_label('Private content').fill('Synthetic private text')
            page.get_by_role('button',name='Save as draft').click()
            page.get_by_text('Browser draft',exact=True).wait_for()
            page.get_by_role('button',name='Publish',exact=True).click()
            page.get_by_role('button',name='Unpublish',exact=True).wait_for()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
            page.get_by_role('button',name='Sign out',exact=True).click()
            page.get_by_role('heading',name='Welcome back.').wait_for()
            assert not errors,errors
            browser.close()
            print('Browser smoke passed: login, service create, draft save, publish, mobile layout, logout.')
    finally:server.shutdown();bridge.close()
