"""JSON menus can be rendered by Telegram clients or inspected in tests."""
async def catalog(store,page=0,size=8):
    if not 0<=page<=100000 or not 1<=size<=20:raise ValueError('Invalid menu page')
    rows=await store.pool.fetch('SELECT service_id,service_name,stars_price,price FROM services WHERE is_active=1 ORDER BY service_id LIMIT $1 OFFSET $2',size+1,page*size)
    return {'kind':'catalog','page':page,'size':size,'has_next':len(rows)>size,
            'items':[{'id':r['service_id'],'label':r['service_name'],'price':{'INR':r['price'],'XTR':r['stars_price']},'action':f"service:{r['service_id']}"} for r in rows[:size]]}
