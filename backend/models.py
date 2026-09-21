from decimal import Decimal
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Login(StrictModel):password:str=Field(min_length=1,max_length=256)
class ServiceCreate(StrictModel):
    service_name:str=Field(min_length=1,max_length=80)
    description:str=Field(min_length=1,max_length=500)
    price:Decimal=Field(gt=0,lt=10000000000,decimal_places=2)
    stars_price:int|None=Field(default=None,ge=1,le=100000,strict=True)
    validity_days:int=Field(default=0,ge=0,le=3650,strict=True)
    delete_after_seconds:int=Field(default=86400,ge=60,le=86400,strict=True)
    is_active:bool=False
class ServicePatch(StrictModel):
    revision:int=Field(ge=1,strict=True)
    service_name:str|None=Field(default=None,min_length=1,max_length=80)
    description:str|None=Field(default=None,min_length=1,max_length=500)
    price:Decimal|None=Field(default=None,gt=0,lt=10000000000,decimal_places=2)
    stars_price:int|None=Field(default=None,ge=1,le=100000,strict=True)
    validity_days:int|None=Field(default=None,ge=0,le=3650,strict=True)
    delete_after_seconds:int|None=Field(default=None,ge=60,le=86400,strict=True)
    is_active:bool|None=None
class EntryCreate(StrictModel):
    title:str=Field(min_length=1,max_length=80)
    text:str=Field(min_length=1,max_length=100000)
class EntryPatch(EntryCreate):revision:int=Field(ge=1,strict=True)
class Publish(StrictModel):
    revision:int=Field(ge=1,strict=True)
    published:bool
class Broadcast(StrictModel):
    text:str=Field(min_length=1,max_length=3000)
    confirmed:Literal[True]
class Ban(StrictModel):is_banned:bool
class Decision(StrictModel):approve:bool
