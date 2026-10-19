import hashlib, os, sys, unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0,ROOT)
import dataplane_contract as d
I='0123456789abcdef0123456789abcdef'; T=bytes(range(1,17)); Z=bytes(16); R=bytes(range(16,32))
def golden():
    return {
      'telemetry':d.encode_telemetry_directory(12345,2,3,I,23456,45001,7,T,9,7),
      'jump':d.encode_jump_directory(12345,4,3,12345,45002,8,T,10,7),
      'envelope':d.encode_envelope(1,12345,12345,7,I,T,Z,b'SCENARIO_ID:1,SPEED:0'),
      'jump_envelope':d.encode_envelope(0x100,12345,23456,8,I,T,R,b'JUMP_STA_TIME:4:43000000')}
class Tests(unittest.TestCase):
 def test_names(self): self.assertEqual(d.telemetry_name(12345,I),'Local\\TSScoringPlugin.v1.12345.App.'+I+'.Telemetry');self.assertEqual(d.jump_name(12345),'Local\\TSScoringPlugin.v1.12345.CurrentJump')
 def test_legacy_jump_names_pid_d4_2a(self):
  # PID-D4 Legacy Jump 2A-alpha (Stage S1, tests first): the Legacy host owns its own Directory name; the Current name is unchanged (STOP-3).
  for fn in ('legacy_jump_name','jump_directory_names'):
   if not hasattr(d,fn):self.fail('[contract:name-resolution-api-missing] dataplane_contract.%s does not exist yet'%fn)
  self.assertEqual(d.legacy_jump_name(12345),'Local\\TSScoringPlugin.v1.12345.LegacyJump')
  self.assertEqual(d.jump_name(12345),'Local\\TSScoringPlugin.v1.12345.CurrentJump')
  self.assertEqual(d.jump_directory_names(12345),(d.jump_name(12345),d.legacy_jump_name(12345)))
  self.assertEqual(d.legacy_jump_name(4294967295),'Local\\TSScoringPlugin.v1.4294967295.LegacyJump')
  for bad in (0,-1,4294967296,'12345',None):
   with self.assertRaisesRegex(ValueError,'pid'):d.legacy_jump_name(bad)
   with self.assertRaisesRegex(ValueError,'pid'):d.jump_directory_names(bad)
 def test_legacy_and_current_jump_names_differ_only_in_the_suffix_pid_d4_2a(self):
  for fn in ('legacy_jump_name','jump_directory_names'):
   if not hasattr(d,fn):self.fail('[contract:name-resolution-api-missing] dataplane_contract.%s does not exist yet'%fn)
  cur,leg=d.jump_directory_names(777)
  self.assertEqual(cur.rsplit('.',1)[0],leg.rsplit('.',1)[0])
  self.assertEqual((cur.rsplit('.',1)[1],leg.rsplit('.',1)[1]),('CurrentJump','LegacyJump'))
  self.assertNotEqual(cur,leg)
 def test_roundtrip(self):
  g=golden();self.assertEqual(d.decode_telemetry_directory(g['telemetry'])['port'],45001);self.assertEqual(d.decode_jump_directory(g['jump'])['port'],45002);self.assertEqual(d.decode_envelope(g['envelope'])['payload'],b'SCENARIO_ID:1,SPEED:0')
 def test_offsets(self):
  g=golden();self.assertEqual(len(g['telemetry']),128);self.assertEqual(len(g['jump']),128);self.assertEqual(g['telemetry'][24:56],I.encode());self.assertEqual(g['envelope'][32:64],I.encode());self.assertEqual(g['envelope'][96:],b'SCENARIO_ID:1,SPEED:0')
 def test_reject(self):
  g=golden();x=bytearray(g['telemetry']);x[16]=3
  with self.assertRaisesRegex(ValueError,'sequence'):d.decode_telemetry_directory(x)
  x=bytearray(g['envelope']);x[0]=0
  with self.assertRaisesRegex(ValueError,'magic'):d.decode_envelope(x)
 def test_csharp_golden(self):
  folder=os.environ.get('PID_D1_CSHARP_GOLDEN')
  if not folder:return
  for name,data in golden().items():
   with open(os.path.join(folder,name+'.bin'),'rb') as f:self.assertEqual(f.read(),data,name)

 def test_closed_and_states(self):
  closed=d.encode_telemetry_directory(12345,6,d.CLOSED,'',0,0,0,bytes(16),11,0)
  self.assertEqual(d.decode_telemetry_directory(closed)['app_instance'],'')
  jump_closed=d.encode_jump_directory(12345,6,d.CLOSED,0,0,0,bytes(16),11,0)
  self.assertEqual(d.decode_jump_directory(jump_closed)['state'],d.CLOSED)
  for state in (d.PUBLISHED,d.PUBLISHED|d.WITHDRAWING):
   raw=d.encode_telemetry_directory(12345,8,state,I,23456,0,0,T,12,0)
   self.assertEqual(d.decode_telemetry_directory(raw)['state'],state)
 def test_address_transport_reserved_and_state_rejection(self):
  g=golden()
  for offset,reason in ((88,'address-family'),(92,'transport'),(100,'reserved')):
   x=bytearray(g['telemetry']);x[offset]=9
   with self.assertRaisesRegex(ValueError,reason):d.decode_telemetry_directory(x)
  x=bytearray(g['jump']);x[56]=9
  with self.assertRaisesRegex(ValueError,'address-family'):d.decode_jump_directory(x)
  x=bytearray(g['jump']);x[60]=9
  with self.assertRaisesRegex(ValueError,'transport'):d.decode_jump_directory(x)
  with self.assertRaisesRegex(ValueError,'state-ready'):d.encode_telemetry_directory(1,2,d.READY,I,2,3,4,T,5,0)
 def test_closed_encoder_rejects_live_fields(self):
  with self.assertRaisesRegex(ValueError,'closed-fields'):d.encode_telemetry_directory(1,2,d.CLOSED,I,2,3,4,T,5,1)
  with self.assertRaisesRegex(ValueError,'closed-fields'):d.encode_jump_directory(1,2,d.CLOSED,1,3,4,T,5,1)
 def test_utf8_rejection(self):
  x=bytearray(golden()['envelope']);x[-1]=0xff
  with self.assertRaisesRegex(ValueError,'utf8'):d.decode_envelope(x)
 def test_hashes_stable(self):
  expected={'telemetry': '92C8EA0ECD886B0052B33315F8359BB22589FB04BD496AEC68D14B9E116928FF', 'jump': '7B47BCA5CF283F037097E7D62D16C60D58DBF6980A67E5C2D21D45770F66D7B6', 'envelope': '3FF6E6F721BFFF2F9186BDB75C344D7771222EF55BE113FCD2590D47948C775C', 'jump_envelope': '9490DE7D60DC39CA3BFE77EA16413CD8BD6B89297AE2C42824919065541FE5D4'}
  self.assertEqual({k:hashlib.sha256(v).hexdigest().upper() for k,v in golden().items()},expected)
if __name__=='__main__':unittest.main()
