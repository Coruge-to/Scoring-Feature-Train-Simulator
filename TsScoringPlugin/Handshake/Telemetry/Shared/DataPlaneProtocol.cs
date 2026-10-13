using System;
using System.Text;

namespace TSScoringPlugin.DataPlane
{
    internal static class DataPlaneProtocol
    {
        public const UInt32 TelemetryMagic = 0x50445453U;
        public const UInt32 JumpMagic = 0x4A445453U;
        public const UInt32 EnvelopeMagic = 0x31445054U;
        public const UInt32 DirectoryVersion = 1U;
        public const UInt16 EnvelopeVersion = 1;
        public const Int32 DirectorySize = 128;
        public const Int32 EnvelopeSize = 96;
        public const UInt32 Published = 1U;
        public const UInt32 Ready = 2U;
        public const UInt32 Withdrawing = 4U;
        public const UInt32 Closed = 8U;
        public const UInt32 KnownStates = 15U;
        public const UInt32 TelemetryKnownCapabilities = 7U;
        public const UInt32 JumpKnownCapabilities = 7U;

        public static string TelemetryName(UInt32 pid, string instance)
        {
            ValidatePid(pid); ValidateInstance(instance);
            return "Local\\TSScoringPlugin.v1." + pid.ToString() + ".App." + instance + ".Telemetry";
        }
        public static string JumpName(UInt32 pid)
        {
            ValidatePid(pid); return "Local\\TSScoringPlugin.v1." + pid.ToString() + ".CurrentJump";
        }
        public static void ValidatePid(UInt32 pid) { if (pid == 0U) throw new ArgumentOutOfRangeException("pid"); }
        public static void ValidateInstance(string value)
        {
            if (value == null || value.Length != 32) throw new ArgumentException("instance");
            for (int i=0;i<value.Length;i++) if (!((value[i]>='0'&&value[i]<='9')||(value[i]>='a'&&value[i]<='f'))) throw new ArgumentException("instance");
        }
        static void ValidateToken(byte[] value, string name) { if (value==null || value.Length!=16) throw new ArgumentException(name); }
        static void U16(byte[] b,int o,UInt16 v){ b[o]=(byte)v;b[o+1]=(byte)(v>>8); }
        static void U32(byte[] b,int o,UInt32 v){ b[o]=(byte)v;b[o+1]=(byte)(v>>8);b[o+2]=(byte)(v>>16);b[o+3]=(byte)(v>>24); }
        static UInt16 R16(byte[] b,int o){ return (UInt16)(b[o]|(b[o+1]<<8)); }
        static UInt32 R32(byte[] b,int o){ return (UInt32)(b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24)); }
        static bool Zero(byte[] b,int o,int n){ for(int i=0;i<n;i++) if(b[o+i]!=0)return false; return true; }
        static byte[] AsciiInstance(string s){ ValidateInstance(s); return Encoding.ASCII.GetBytes(s); }
        static string ReadInstance(byte[] b,int o){ string s=Encoding.ASCII.GetString(b,o,32); ValidateInstance(s); return s; }
        static void State(UInt32 state, bool usable)
        {
            if ((state & ~KnownStates)!=0U) throw new ArgumentException("state-flags");
            if ((state & Ready)!=0U && (state & Published)==0U) throw new ArgumentException("state-ready");
            if ((state & Withdrawing)!=0U && ((state & Published)==0U || (state & Closed)!=0U)) throw new ArgumentException("state-withdrawing");
            if ((state & Closed)!=0U && state!=Closed) throw new ArgumentException("state-closed");
            if (usable && ((state&(Published|Ready))!=(Published|Ready) || (state&(Withdrawing|Closed))!=0U)) throw new ArgumentException("state-not-usable");
        }
        static void Open(byte[] b,int size){ if(b==null||b.Length!=size)throw new ArgumentException("size"); }
        static void Sequence(byte[] b){ UInt32 h=R32(b,16), t=R32(b,124); if((h&1U)!=0U||h!=t)throw new ArgumentException("sequence"); }
        static void Reserved(byte[] b,int start,int end){ if(!Zero(b,start,end-start))throw new ArgumentException("reserved"); }

        public static byte[] EncodeTelemetryDirectory(UInt32 bvePid, UInt32 seq, UInt32 state, string instance, UInt32 appPid, UInt32 port, UInt32 generation, byte[] token, UInt32 change, UInt32 caps)
        {
            ValidatePid(bvePid); ValidateToken(token,"token"); State(state,false); if((seq&1U)!=0U)throw new ArgumentException("sequence"); byte[] b=new byte[128];
            U32(b,0,TelemetryMagic);U32(b,4,1);U32(b,8,128);U32(b,12,bvePid);U32(b,16,seq);U32(b,20,state);
            if(state==Closed){if(!String.IsNullOrEmpty(instance)||appPid!=0||port!=0||generation!=0||!Zero(token,0,16)||caps!=0)throw new ArgumentException("closed-fields");}
            else{Array.Copy(AsciiInstance(instance),0,b,24,32);}
            U32(b,56,appPid);U32(b,60,port);U32(b,64,generation);Array.Copy(token,0,b,68,16);
            U32(b,84,change);U32(b,88,4);U32(b,92,1);U32(b,96,caps);U32(b,124,seq);return b;
        }
        public static TelemetryDirectory DecodeTelemetryDirectory(byte[] b)
        {
            Open(b,128);if(R32(b,0)!=TelemetryMagic)throw new ArgumentException("magic");if(R32(b,4)!=1)throw new ArgumentException("version");if(R32(b,8)!=128)throw new ArgumentException("block-size");Sequence(b);Reserved(b,100,124);
            UInt32 pid=R32(b,12),state=R32(b,20),port=R32(b,60),gen=R32(b,64),caps=R32(b,96);ValidatePid(pid);State(state,false);if(R32(b,88)!=4)throw new ArgumentException("address-family");if(R32(b,92)!=1)throw new ArgumentException("transport");if((caps&~TelemetryKnownCapabilities)!=0)throw new ArgumentException("capabilities");
            string instance=state==Closed?String.Empty:ReadInstance(b,24); bool usable=(state&(Published|Ready))==(Published|Ready)&&(state&(Withdrawing|Closed))==0;
            if(usable){State(state,true);if(port==0||port>65535||gen==0||Zero(b,68,16))throw new ArgumentException("endpoint");}
            if(state==Closed && (!Zero(b,24,32)||R32(b,56)!=0||port!=0||gen!=0||!Zero(b,68,16)||caps!=0))throw new ArgumentException("closed-fields");
            return new TelemetryDirectory(pid,state,instance,R32(b,56),port,gen,Slice(b,68,16),R32(b,84),caps);
        }
        public static byte[] EncodeJumpDirectory(UInt32 bvePid,UInt32 seq,UInt32 state,UInt32 publisherPid,UInt32 port,UInt32 generation,byte[] token,UInt32 change,UInt32 caps)
        {
            ValidatePid(bvePid);ValidateToken(token,"token");State(state,false);if((seq&1U)!=0U)throw new ArgumentException("sequence");if(state==Closed&&(publisherPid!=0||port!=0||generation!=0||!Zero(token,0,16)||caps!=0))throw new ArgumentException("closed-fields");byte[] b=new byte[128];U32(b,0,JumpMagic);U32(b,4,1);U32(b,8,128);U32(b,12,bvePid);U32(b,16,seq);U32(b,20,state);U32(b,24,publisherPid);U32(b,28,port);U32(b,32,generation);Array.Copy(token,0,b,36,16);U32(b,52,change);U32(b,56,4);U32(b,60,1);U32(b,64,caps);U32(b,124,seq);return b;
        }
        public static JumpDirectory DecodeJumpDirectory(byte[] b)
        {
            Open(b,128);if(R32(b,0)!=JumpMagic)throw new ArgumentException("magic");if(R32(b,4)!=1)throw new ArgumentException("version");if(R32(b,8)!=128)throw new ArgumentException("block-size");Sequence(b);Reserved(b,68,124);
            UInt32 pid=R32(b,12),state=R32(b,20),pub=R32(b,24),port=R32(b,28),gen=R32(b,32),caps=R32(b,64);ValidatePid(pid);State(state,false);if(R32(b,56)!=4)throw new ArgumentException("address-family");if(R32(b,60)!=1)throw new ArgumentException("transport");if((caps&~JumpKnownCapabilities)!=0)throw new ArgumentException("capabilities");bool usable=(state&(Published|Ready))==(Published|Ready)&&(state&(Withdrawing|Closed))==0;
            if(usable){State(state,true);if(pub!=pid||port==0||port>65535||gen==0||Zero(b,36,16))throw new ArgumentException("endpoint");}
            if(state==Closed&&(pub!=0||port!=0||gen!=0||!Zero(b,36,16)||caps!=0))throw new ArgumentException("closed-fields");
            return new JumpDirectory(pid,state,pub,port,gen,Slice(b,36,16),R32(b,52),caps);
        }
        public static byte[] EncodeEnvelope(UInt32 type,UInt32 bvePid,UInt32 senderPid,UInt32 generation,string instance,byte[] token,byte[] requestId,byte[] payload)
        {
            ValidatePid(bvePid);ValidatePid(senderPid);ValidateToken(token,"token");ValidateToken(requestId,"requestId");if(payload==null)throw new ArgumentNullException("payload");if(payload.Length>65411)throw new ArgumentException("payload-size");
            byte[] b=new byte[96+payload.Length];U32(b,0,EnvelopeMagic);U16(b,4,1);U16(b,6,96);U32(b,8,type);U32(b,12,0);U32(b,16,bvePid);U32(b,20,senderPid);U32(b,24,generation);U32(b,28,(UInt32)payload.Length);Array.Copy(AsciiInstance(instance),0,b,32,32);Array.Copy(token,0,b,64,16);Array.Copy(requestId,0,b,80,16);Array.Copy(payload,0,b,96,payload.Length);return b;
        }
        public static Envelope DecodeEnvelope(byte[] b)
        {
            if(b==null||b.Length<96)throw new ArgumentException("size");if(R32(b,0)!=EnvelopeMagic)throw new ArgumentException("magic");if(R16(b,4)!=1)throw new ArgumentException("version");if(R16(b,6)!=96)throw new ArgumentException("header-size");if(R32(b,12)!=0)throw new ArgumentException("flags");UInt32 n=R32(b,28);if(n!=b.Length-96)throw new ArgumentException("payload-length");
            string instance=ReadInstance(b,32);if(R32(b,16)==0||R32(b,20)==0||R32(b,24)==0||Zero(b,64,16))throw new ArgumentException("identity");try{new UTF8Encoding(false,true).GetString(b,96,(int)n);}catch(DecoderFallbackException){throw new ArgumentException("utf8");}UInt32 type=R32(b,8);bool reqZero=Zero(b,80,16);if(type>=1&&type<=4&&!reqZero)throw new ArgumentException("request-id");if((type==5||type==0x100||type==0x101)&&reqZero)throw new ArgumentException("request-id");if(!((type>=1&&type<=5)||type==0x100||type==0x101))throw new ArgumentException("message-type");
            return new Envelope(type,R32(b,16),R32(b,20),R32(b,24),instance,Slice(b,64,16),Slice(b,80,16),Slice(b,96,(int)n));
        }
        static byte[] Slice(byte[] b,int o,int n){byte[] r=new byte[n];Array.Copy(b,o,r,0,n);return r;}
    }
    internal sealed class TelemetryDirectory{public readonly UInt32 BvePid,State,AppPid,Port,Generation,ChangeCount,Capabilities;public readonly string AppInstance;public readonly byte[] Token;public TelemetryDirectory(UInt32 a,UInt32 b,string c,UInt32 d,UInt32 e,UInt32 f,byte[] g,UInt32 h,UInt32 i){BvePid=a;State=b;AppInstance=c;AppPid=d;Port=e;Generation=f;Token=g;ChangeCount=h;Capabilities=i;}}
    internal sealed class JumpDirectory{public readonly UInt32 BvePid,State,PublisherPid,Port,Generation,ChangeCount,Capabilities;public readonly byte[] Token;public JumpDirectory(UInt32 a,UInt32 b,UInt32 c,UInt32 d,UInt32 e,byte[] f,UInt32 g,UInt32 h){BvePid=a;State=b;PublisherPid=c;Port=d;Generation=e;Token=f;ChangeCount=g;Capabilities=h;}}
    internal sealed class Envelope{public readonly UInt32 MessageType,BvePid,SenderPid,Generation;public readonly string AppInstance;public readonly byte[] Token,RequestId,Payload;public Envelope(UInt32 a,UInt32 b,UInt32 c,UInt32 d,string e,byte[] f,byte[] g,byte[] h){MessageType=a;BvePid=b;SenderPid=c;Generation=d;AppInstance=e;Token=f;RequestId=g;Payload=h;}}
}