"""Owner-only content CRUD, portable backup/restore, and private data imports."""
import asyncio
import base64
import io
import json
from html import escape
from aiogram import Router,F
from aiogram.filters import Command
from aiogram.types import Message,CallbackQuery,BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError
from .states import Owner
from .ui import ADMIN,CANCEL,keyboard
from .backup import seal,unseal,validate,export_content,import_content,MAX_BYTES

router=Router()

def stage(cipher,value):
    return cipher.cipher.encrypt(json.dumps(value,ensure_ascii=False).encode()).decode()

def unstage(cipher,value):
    return json.loads(cipher.cipher.decrypt(value.encode()))

async def remove_input(m):
    try:await m.delete()
    except TelegramAPIError:
        await m.answer('Could not remove your input message. Please delete it manually.')

async def show_services(m,store):
    rows=await store.pool.fetch('SELECT service_id,service_name FROM services ORDER BY service_id')
    # Batches keep Telegram keyboards bounded even after many imports.
    for start in range(0,len(rows),30):
        await m.answer('<b>🔐 Choose a service to manage</b>',reply_markup=keyboard(*[
            [(f"{r['service_id']} • {r['service_name']}",f"content:list:{r['service_id']}:0")] for r in rows[start:start+30]]))

async def show_entries(m,store,sid,page=0):
    s=await store.pool.fetchrow('SELECT * FROM services WHERE service_id=$1',sid)
    if not s:raise ValueError('Unknown service.')
    rows=await store.pool.fetch('SELECT data_id,title,is_published FROM vault_data WHERE service_id=$1 ORDER BY data_id LIMIT 15 OFFSET $2',sid,max(0,page)*15)
    buttons=[[(('🟢 ' if r['is_published'] else '📝 ')+r['title'],f"content:entry:{r['data_id']}")] for r in rows]
    buttons+=[[('➕ Add text / TXT file',f'content:add:{sid}')],[('⬅️ Previous',f'content:list:{sid}:{max(0,page-1)}'),('Next ➡️',f'content:list:{sid}:{page+1}')]]
    await m.answer(f"<b>{escape(s['service_name'])}</b>\n📝 Drafts are owner-only. 🟢 Published entries are delivered to paid users.\nService active: {bool(s['is_active'])}",reply_markup=keyboard(*buttons))

@router.callback_query(F.data.startswith('content:'))
async def action(q:CallbackQuery,state:FSMContext,store,cipher):
    parts=q.data.split(':');verb=parts[1]
    await q.answer()
    if verb!='import_confirm':
        await state.clear()
    if verb=='list':
        await state.clear()
        await show_entries(q.message,store,int(parts[2]),int(parts[3]))
    elif verb=='add':
        sid=int(parts[2])
        if not await store.pool.fetchval('SELECT EXISTS(SELECT 1 FROM services WHERE service_id=$1)',sid):raise ValueError('Unknown service.')
        await state.clear();await state.set_state(Owner.content_title);await state.update_data(sid=sid)
        await q.message.answer('Send a short title (1–80 characters). Then send the text or a UTF-8 .txt file.',reply_markup=CANCEL)
    elif verb in {'entry','preview','edit','rename','publish','unpublish','delete','delete_confirm'}:
        did=int(parts[2])
        r=await store.pool.fetchrow('SELECT * FROM vault_data WHERE data_id=$1',did)
        if not r:raise ValueError('Entry no longer exists.')
        if verb=='entry':
            await state.clear()
            await q.message.answer(f"<b>{escape(r['title'])}</b>\nEntry ID: {did}\n{'Published' if r['is_published'] else 'Draft / unverified reference'}",reply_markup=keyboard(
                [('👁 Preview',f'content:preview:{did}'),('✏️ Edit text',f'content:edit:{did}')],
                [('🏷 Rename',f'content:rename:{did}'),('📝 Unpublish' if r['is_published'] else '🟢 Publish',f"content:{'unpublish' if r['is_published'] else 'publish'}:{did}")],
                [('🗑 Delete',f'content:delete:{did}'),('⬅️ Entries',f"content:list:{r['service_id']}:0")]))
        elif verb=='preview':
            from .workers import chunks
            for part in chunks(cipher.decrypt(r['service_id'],r['encrypted_payload'])):
                msg=await q.message.answer('<b>Owner preview • unverified unless independently reviewed</b>\n'+escape(part),protect_content=True)
                await store.pool.execute('INSERT INTO deletion_jobs(chat_id,message_id,due_at) VALUES($1,$2,now()+3600)',q.from_user.id,msg.message_id)
        elif verb in {'edit','rename'}:
            await state.clear();await state.set_state(Owner.edit_content if verb=='edit' else Owner.rename_content)
            await state.update_data(did=did)
            await q.message.answer('Send replacement text / UTF-8 .txt file. Editing returns the entry to draft.' if verb=='edit' else 'Send the new title (1–80 characters).',reply_markup=CANCEL)
        elif verb=='publish':
            # Never infer correctness from publishing; operator chooses when ready.
            await store.pool.execute('UPDATE vault_data SET is_published=1 WHERE data_id=$1',did)
            await store.audit(q.from_user.id,'publish',did)
            await q.message.answer('🟢 Published. Paid users can receive this entry when the service is active.',reply_markup=ADMIN)
        elif verb=='unpublish':
            await store.pool.execute('UPDATE vault_data SET is_published=0 WHERE data_id=$1',did)
            await store.audit(q.from_user.id,'unpublish',did)
            await q.message.answer('📝 Returned to draft.',reply_markup=ADMIN)
        elif verb=='delete':
            await q.message.answer('Delete this entry permanently? Previously delivered messages cannot be recalled by this action.',reply_markup=keyboard([('🗑 Confirm delete',f'content:delete_confirm:{did}')],[('Keep entry',f'content:entry:{did}')]))
        else:
            await store.pool.execute('DELETE FROM vault_data WHERE data_id=$1',did)
            await store.audit(q.from_user.id,'delete_entry',did)
            await q.message.answer('Entry deleted.',reply_markup=ADMIN)
    elif verb=='backup':
        await begin_backup(q.message,state)
    elif verb=='restore':
        await state.clear()
        await q.message.answer('Choose a private file import. Imported services start disabled and all entries remain drafts.',reply_markup=keyboard([('📦 Restore .vault backup','content:restore_file')],[('📄 Import reference JSON','content:import_file')]))
    elif verb in {'restore_file','import_file'}:
        await state.clear();await state.set_state(Owner.restore_file if verb=='restore_file' else Owner.import_file)
        await q.message.answer('Upload the .vault file.' if verb=='restore_file' else 'Upload UTF-8 JSON in research-content-v1 format (see docs/content-import.example.json). For plain text, use Add in the content menu.',reply_markup=CANCEL)
    elif verb=='import_confirm':
        if await state.get_state() not in {Owner.import_confirm.state,Owner.restore_confirm.state}:raise ValueError('Import session expired.')
        data=await state.get_data()
        ids=await import_content(store,cipher,unstage(cipher,data['bundle']),q.from_user.id)
        await state.clear()
        await q.message.edit_reply_markup(reply_markup=None)
        await q.message.answer('✅ Imported as drafts. New disabled service IDs: '+', '.join(map(str,ids))+'.\nReview entries, publish the ones you want to sell, configure prices and activate each service in Service Settings.',reply_markup=ADMIN)

@router.message(Command('backup'))
async def backup_command(m:Message,state:FSMContext):await begin_backup(m,state)

async def begin_backup(m,state):
    await state.clear();await state.set_state(Owner.backup_password)
    await m.answer('Choose a NEW backup password (16–256 characters). It protects your content export. Keep it in your password manager. Your next message will be deleted where Telegram allows. This is a cloud bot chat, not end-to-end encrypted.',reply_markup=CANCEL)

@router.message(Command('restore'))
async def restore_command(m:Message,state:FSMContext):
    await state.clear();await state.set_state(Owner.restore_file)
    await m.answer('Upload your password-encrypted .vault content backup.',reply_markup=CANCEL)

@router.message(Command('import'))
async def import_command(m:Message,state:FSMContext):
    await state.clear();await state.set_state(Owner.import_file)
    await m.answer('Upload your private research-content-v1 JSON file. Imported data remains unpublished.',reply_markup=CANCEL)

@router.message(Owner.content_title,F.text)
async def title(m:Message,state:FSMContext):
    if not 1<=len(m.text)<=80:raise ValueError('Title must have 1–80 characters.')
    await state.update_data(title=m.text)
    await state.set_state(Owner.content_text)
    await m.answer('Now send the reference text or a UTF-8 .txt file.',reply_markup=CANCEL)

async def read_text(m,bot):
    if m.text:return m.text
    if not m.document or not (m.document.file_name or '').lower().endswith('.txt') or not m.document.file_size or m.document.file_size>100000:
        raise ValueError('Send text or a UTF-8 .txt file of at most 100 KB.')
    out=io.BytesIO();await bot.download(m.document,destination=out)
    return out.getvalue().decode('utf-8-sig')

@router.message(Owner.content_text)
async def add(m:Message,state:FSMContext,store,cipher,bot):
    text=await read_text(m,bot)
    data=await state.get_data()
    token=cipher.encrypt(data['sid'],text)
    did=await store.pool.fetchval('INSERT INTO vault_data(service_id,title,encrypted_payload) VALUES($1,$2,$3) RETURNING data_id',data['sid'],data['title'],token)
    await remove_input(m)
    await store.audit(m.from_user.id,'add_draft',did)
    await state.clear()
    await m.answer('🔐 Saved encrypted as a draft.',reply_markup=keyboard([('Review entry',f'content:entry:{did}')]))

@router.message(Owner.edit_content)
async def edit(m:Message,state:FSMContext,store,cipher,bot):
    text=await read_text(m,bot);did=(await state.get_data())['did']
    r=await store.pool.fetchrow('SELECT * FROM vault_data WHERE data_id=$1',did)
    if not r:raise ValueError('Entry no longer exists.')
    await store.pool.execute('UPDATE vault_data SET encrypted_payload=$2,is_published=0 WHERE data_id=$1',did,cipher.encrypt(r['service_id'],text))
    await remove_input(m);await store.audit(m.from_user.id,'edit_draft',did);await state.clear()
    await m.answer('✅ Updated and returned to draft. Review and publish when ready.',reply_markup=keyboard([('Review entry',f'content:entry:{did}')]))

@router.message(Owner.rename_content,F.text)
async def rename(m:Message,state:FSMContext,store):
    if not 1<=len(m.text)<=80:raise ValueError('Title must have 1–80 characters.')
    did=(await state.get_data())['did']
    await store.pool.execute('UPDATE vault_data SET title=$2 WHERE data_id=$1',did,m.text)
    await store.audit(m.from_user.id,'rename_entry',did);await state.clear()
    await m.answer('Title updated.',reply_markup=ADMIN)

@router.message(Owner.backup_password,F.text)
async def backup_password(m:Message,state:FSMContext,store,cipher):
    password=m.text
    await remove_input(m)
    bundle=await export_content(store,cipher)
    blob=await asyncio.to_thread(seal,bundle,password)
    # Deliverable intentionally downloadable; its research content is password-encrypted.
    await m.answer_document(BufferedInputFile(blob,filename='research-content.vault'),caption='Password-encrypted content backup. Download and keep it somewhere independent of this server. Users/payment history are not included.',protect_content=False)
    await store.audit(m.from_user.id,'content_backup','export');await state.clear()

async def read_file(m,bot,suffix):
    d=m.document
    if not d or not (d.file_name or '').lower().endswith(suffix) or not d.file_size or d.file_size>MAX_BYTES:
        raise ValueError(f'Upload a {suffix} file smaller than 5 MB.')
    out=io.BytesIO();await bot.download(d,destination=out)
    return out.getvalue()

@router.message(Owner.restore_file,F.document)
async def restore_file(m:Message,state:FSMContext,cipher,bot):
    blob=await read_file(m,bot,'.vault')
    await state.update_data(blob=stage(cipher,base64.b64encode(blob).decode()))
    await remove_input(m);await state.set_state(Owner.restore_password)
    await m.answer('Send the backup password. It is used in memory and not saved.',reply_markup=CANCEL)

async def preview_import(m,state,cipher,bundle,restore=False):
    await state.update_data(bundle=stage(cipher,bundle))
    await state.set_state(Owner.restore_confirm if restore else Owner.import_confirm)
    count=sum(len(s['entries']) for s in bundle['services'])
    await m.answer(f"Import {len(bundle['services'])} new disabled services and {count} draft entries?\nExisting content, prices, users and purchases will not be overwritten.",reply_markup=keyboard([('✅ Import as drafts','content:import_confirm')],[('✖️ Cancel','cancel')]))

@router.message(Owner.restore_password,F.text)
async def restore_password(m:Message,state:FSMContext,cipher):
    password=m.text;await remove_input(m)
    blob=base64.b64decode(unstage(cipher,(await state.get_data())['blob']))
    bundle=await asyncio.to_thread(unseal,blob,password)
    await preview_import(m,state,cipher,bundle,True)

@router.message(Owner.import_file,F.document)
async def import_file(m:Message,state:FSMContext,cipher,bot):
    raw=await read_file(m,bot,'.json')
    bundle=validate(json.loads(raw.decode('utf-8-sig')))
    await remove_input(m)
    await preview_import(m,state,cipher,bundle)
