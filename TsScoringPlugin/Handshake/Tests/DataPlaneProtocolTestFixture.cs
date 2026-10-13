using System;using System.IO;using System.Text;using TSScoringPlugin.DataPlane;
public static class DataPlaneProtocolTestFixture
{
 public static void WriteGolden(string folder)
 {
  Directory.CreateDirectory(folder);string i="0123456789abcdef0123456789abcdef";byte[] t=new byte[16],z=new byte[16],r=new byte[16];for(int n=0;n<16;n++){t[n]=(byte)(n+1);r[n]=(byte)(n+16);}
  File.WriteAllBytes(Path.Combine(folder,"telemetry.bin"),DataPlaneProtocol.EncodeTelemetryDirectory(12345,2,3,i,23456,45001,7,t,9,7));
  File.WriteAllBytes(Path.Combine(folder,"jump.bin"),DataPlaneProtocol.EncodeJumpDirectory(12345,4,3,12345,45002,8,t,10,7));
  File.WriteAllBytes(Path.Combine(folder,"envelope.bin"),DataPlaneProtocol.EncodeEnvelope(1,12345,12345,7,i,t,z,Encoding.UTF8.GetBytes("SCENARIO_ID:1,SPEED:0")));
  File.WriteAllBytes(Path.Combine(folder,"jump_envelope.bin"),DataPlaneProtocol.EncodeEnvelope(0x100,12345,23456,8,i,t,r,Encoding.UTF8.GetBytes("JUMP_STA_TIME:4:43000000")));
  if(DataPlaneProtocol.DecodeTelemetryDirectory(File.ReadAllBytes(Path.Combine(folder,"telemetry.bin"))).Port!=45001)throw new Exception("telemetry-roundtrip");
  if(DataPlaneProtocol.DecodeJumpDirectory(File.ReadAllBytes(Path.Combine(folder,"jump.bin"))).Port!=45002)throw new Exception("jump-roundtrip");
  if(DataPlaneProtocol.DecodeEnvelope(File.ReadAllBytes(Path.Combine(folder,"envelope.bin"))).Payload.Length==0)throw new Exception("envelope-roundtrip");
  byte[] closed=DataPlaneProtocol.EncodeTelemetryDirectory(12345,6,DataPlaneProtocol.Closed,String.Empty,0,0,0,new byte[16],11,0);
  if(DataPlaneProtocol.DecodeTelemetryDirectory(closed).AppInstance!=String.Empty)throw new Exception("closed-roundtrip");
  byte[] bad=(byte[])File.ReadAllBytes(Path.Combine(folder,"telemetry.bin")).Clone();bad[88]=9;ExpectReject(delegate{DataPlaneProtocol.DecodeTelemetryDirectory(bad);},"address-family");
  bad=(byte[])File.ReadAllBytes(Path.Combine(folder,"telemetry.bin")).Clone();bad[92]=9;ExpectReject(delegate{DataPlaneProtocol.DecodeTelemetryDirectory(bad);},"transport");
  bad=(byte[])File.ReadAllBytes(Path.Combine(folder,"telemetry.bin")).Clone();bad[100]=1;ExpectReject(delegate{DataPlaneProtocol.DecodeTelemetryDirectory(bad);},"reserved");
  bad=(byte[])File.ReadAllBytes(Path.Combine(folder,"envelope.bin")).Clone();bad[bad.Length-1]=0xff;ExpectReject(delegate{DataPlaneProtocol.DecodeEnvelope(bad);},"utf8");
 }
 static void ExpectReject(Action action,string name){try{action();throw new Exception("missing-rejection-"+name);}catch(ArgumentException){}}

}