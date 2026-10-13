import re, struct
TELEMETRY_MAGIC=0x50445453; JUMP_MAGIC=0x4A445453; ENVELOPE_MAGIC=0x31445054
DIRECTORY_SIZE=128; ENVELOPE_SIZE=96
PUBLISHED=1; READY=2; WITHDRAWING=4; CLOSED=8
_INST=re.compile(r"^[0-9a-f]{32}$")
def _pid(v):
    if not isinstance(v,int) or not (1<=v<=0xffffffff): raise ValueError("pid")
def _instance(v):
    if not isinstance(v,str) or not _INST.fullmatch(v): raise ValueError("instance")
def _token(v,n):
    v=bytes(v)
    if len(v)!=16: raise ValueError(n)
    return v
def telemetry_name(pid,instance): _pid(pid);_instance(instance);return f"Local\\TSScoringPlugin.v1.{pid}.App.{instance}.Telemetry"
def jump_name(pid): _pid(pid);return f"Local\\TSScoringPlugin.v1.{pid}.CurrentJump"
def _state(v,usable=False):
    if v&~15: raise ValueError("state-flags")
    if v&READY and not v&PUBLISHED: raise ValueError("state-ready")
    if v&WITHDRAWING and (not v&PUBLISHED or v&CLOSED): raise ValueError("state-withdrawing")
    if v&CLOSED and v!=CLOSED: raise ValueError("state-closed")
    if usable and ((v&(PUBLISHED|READY))!=(PUBLISHED|READY) or v&(WITHDRAWING|CLOSED)): raise ValueError("state-not-usable")
def encode_telemetry_directory(pid,seq,state,instance,app_pid,port,generation,token,change,caps):
    _pid(pid);token=_token(token,"token");_state(state)
    if seq&1: raise ValueError('sequence')
    if state==CLOSED:
        if instance not in ('',None) or app_pid or port or generation or any(token) or caps: raise ValueError('closed-fields')
        instance_bytes=bytes(32)
    else:
        _instance(instance);instance_bytes=instance.encode('ascii')
    b=bytearray(128);struct.pack_into('<IIIIII',b,0,TELEMETRY_MAGIC,1,128,pid,seq,state);b[24:56]=instance_bytes;struct.pack_into('<III',b,56,app_pid,port,generation);b[68:84]=token;struct.pack_into('<IIII',b,84,change,4,1,caps);struct.pack_into('<I',b,124,seq);return bytes(b)
def decode_telemetry_directory(b):
    b=bytes(b)
    if len(b)!=128: raise ValueError('size')
    magic,ver,size,pid,head,state=struct.unpack_from('<IIIIII',b,0)
    if magic!=TELEMETRY_MAGIC: raise ValueError('magic')
    if ver!=1: raise ValueError('version')
    if size!=128: raise ValueError('block-size')
    if head&1 or head!=struct.unpack_from('<I',b,124)[0]: raise ValueError('sequence')
    if any(b[100:124]): raise ValueError('reserved')
    _pid(pid);inst='' if state==CLOSED else b[24:56].decode('ascii');
    if state!=CLOSED: _instance(inst)
    app,port,gen=struct.unpack_from('<III',b,56);token=b[68:84];change,af,tr,caps=struct.unpack_from('<IIII',b,84);_state(state)
    if af!=4: raise ValueError('address-family')
    if tr!=1: raise ValueError('transport')
    if caps&~7: raise ValueError('capabilities')
    usable=(state&(PUBLISHED|READY))==(PUBLISHED|READY) and not state&(WITHDRAWING|CLOSED)
    if usable and (not 1<=port<=65535 or not gen or not any(token)): raise ValueError('endpoint')
    if state==CLOSED and (any(b[24:56]) or app or port or gen or any(token) or caps): raise ValueError('closed-fields')
    return dict(bve_pid=pid,state=state,app_instance=inst,app_pid=app,port=port,generation=gen,token=token,change_count=change,capabilities=caps)
def encode_jump_directory(pid,seq,state,publisher_pid,port,generation,token,change,caps):
    _pid(pid);token=_token(token,'token');_state(state)
    if seq&1: raise ValueError('sequence')
    if state==CLOSED and (publisher_pid or port or generation or any(token) or caps): raise ValueError('closed-fields')
    b=bytearray(128);struct.pack_into('<IIIIIII',b,0,JUMP_MAGIC,1,128,pid,seq,state,publisher_pid);struct.pack_into('<II',b,28,port,generation);b[36:52]=token;struct.pack_into('<IIII',b,52,change,4,1,caps);struct.pack_into('<I',b,124,seq);return bytes(b)
def decode_jump_directory(b):
    b=bytes(b)
    if len(b)!=128: raise ValueError('size')
    magic,ver,size,pid,head,state,pub=struct.unpack_from('<IIIIIII',b,0)
    if magic!=JUMP_MAGIC: raise ValueError('magic')
    if ver!=1: raise ValueError('version')
    if size!=128: raise ValueError('block-size')
    if head&1 or head!=struct.unpack_from('<I',b,124)[0]: raise ValueError('sequence')
    if any(b[68:124]): raise ValueError('reserved')
    _pid(pid);port,gen=struct.unpack_from('<II',b,28);token=b[36:52];change,af,tr,caps=struct.unpack_from('<IIII',b,52);_state(state)
    if af!=4: raise ValueError('address-family')
    if tr!=1: raise ValueError('transport')
    if caps&~7: raise ValueError('capabilities')
    usable=(state&(PUBLISHED|READY))==(PUBLISHED|READY) and not state&(WITHDRAWING|CLOSED)
    if usable and (pub!=pid or not 1<=port<=65535 or not gen or not any(token)): raise ValueError('endpoint')
    if state==CLOSED and (pub or port or gen or any(token) or caps): raise ValueError('closed-fields')
    return dict(bve_pid=pid,state=state,publisher_pid=pub,port=port,generation=gen,token=token,change_count=change,capabilities=caps)
def encode_envelope(message_type,bve_pid,sender_pid,generation,instance,token,request_id,payload):
    _pid(bve_pid);_pid(sender_pid);_instance(instance);token=_token(token,'token');request_id=_token(request_id,'request_id');payload=bytes(payload)
    if len(payload)>65411: raise ValueError('payload-size')
    b=bytearray(96+len(payload));struct.pack_into('<IHHIIII',b,0,ENVELOPE_MAGIC,1,96,message_type,0,bve_pid,sender_pid);struct.pack_into('<II',b,24,generation,len(payload));b[32:64]=instance.encode('ascii');b[64:80]=token;b[80:96]=request_id;b[96:]=payload;return bytes(b)
def decode_envelope(b):
    b=bytes(b)
    if len(b)<96: raise ValueError('size')
    magic,ver,hsize,mtype,flags,pid,sender,gen,n=struct.unpack_from('<IHHIIIIII',b,0)
    if magic!=ENVELOPE_MAGIC: raise ValueError('magic')
    if ver!=1: raise ValueError('version')
    if hsize!=96: raise ValueError('header-size')
    if flags: raise ValueError('flags')
    if n!=len(b)-96: raise ValueError('payload-length')
    inst=b[32:64].decode('ascii');_instance(inst);token=b[64:80];req=b[80:96]
    try: b[96:].decode('utf-8','strict')
    except UnicodeDecodeError: raise ValueError('utf8')
    if not pid or not sender or not gen or not any(token): raise ValueError('identity')
    if mtype in (1,2,3,4) and any(req): raise ValueError('request-id')
    if mtype in (5,0x100,0x101) and not any(req): raise ValueError('request-id')
    if mtype not in (1,2,3,4,5,0x100,0x101): raise ValueError('message-type')
    return dict(message_type=mtype,bve_pid=pid,sender_pid=sender,generation=gen,app_instance=inst,token=token,request_id=req,payload=b[96:])
