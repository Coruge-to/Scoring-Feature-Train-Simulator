using System;
using System.IO.MemoryMappedFiles;
using System.Text;

namespace TSScoringPlugin.DataPlane
{
    internal sealed class TelemetryEndpoint
    {
        internal readonly UInt32 BveProcessId;
        internal readonly string AppInstance;
        internal readonly UInt32 AppProcessId;
        internal readonly UInt32 Port;
        internal readonly UInt32 Generation;
        internal readonly byte[] Token;
        internal readonly UInt32 ChangeCount;
        internal readonly UInt32 Capabilities;
        internal TelemetryEndpoint(UInt32 bveProcessId, string appInstance, UInt32 appProcessId, UInt32 port, UInt32 generation, byte[] token, UInt32 changeCount, UInt32 capabilities)
        {
            BveProcessId=bveProcessId;AppInstance=appInstance;AppProcessId=appProcessId;Port=port;Generation=generation;Token=token;ChangeCount=changeCount;Capabilities=capabilities;
        }
    }

    internal static class TelemetryDirectoryReader
    {
        internal const string AppDirectoryMissing="app-directory-missing";
        internal const string AppDirectoryTorn="app-directory-torn";
        internal const string AppDirectoryInvalid="app-directory-invalid";
        internal const string AppDirectoryNotReady="app-directory-not-ready";
        internal const string TelemetryDirectoryMissing="telemetry-directory-missing";
        internal const string TelemetryDirectoryTorn="telemetry-directory-torn";
        internal const string TelemetryDirectoryInvalid="telemetry-directory-invalid";
        internal const string TelemetryNotReady="telemetry-not-ready";
        internal const string BvePidMismatch="bve-pid-mismatch";
        internal const string AppInstanceMismatch="app-instance-mismatch";
        internal const string AppPidMismatch="app-pid-mismatch";
        internal const string Ok="ok";
        internal const int AppDirectorySize=80;
        private const UInt32 AppMagic=0x44415354U;
        private const UInt32 AppVersion=1U;
        private const UInt32 InstancePublished=1U;
        private const UInt32 ProcessStarted=2U;
        private const UInt32 ReadyAccepted=4U;
        private const UInt32 Withdrawing=8U;
        private const UInt32 Closed=16U;

        internal static bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            endpoint=null;reason=AppDirectoryInvalid;
            if(bveProcessId<=0){reason=BvePidMismatch;return false;}
            byte[] appBytes;
            string appName="Local\\TSScoringPlugin.v1."+bveProcessId.ToString()+".AppDirectory";
            if(!TryReadStable(appName,AppDirectorySize,out appBytes,out reason,AppDirectoryMissing,AppDirectoryTorn))return false;
            UInt32 appPid;string instance;UInt32 appFlags;
            try
            {
                if(R32(appBytes,0)!=AppMagic||R32(appBytes,4)!=AppVersion||R32(appBytes,8)!=AppDirectorySize)throw new ArgumentException();
                if(R32(appBytes,12)!=(UInt32)bveProcessId){reason=BvePidMismatch;return false;}
                appFlags=R32(appBytes,20);
                if((appFlags&~31U)!=0U||!Zero(appBytes,64,12))throw new ArgumentException();
                if((appFlags&Closed)!=0U){reason=AppDirectoryNotReady;return false;}
                UInt32 required=InstancePublished|ProcessStarted|ReadyAccepted;
                if((appFlags&required)!=required||(appFlags&Withdrawing)!=0U){reason=AppDirectoryNotReady;return false;}
                instance=Encoding.ASCII.GetString(appBytes,24,32);DataPlaneProtocol.ValidateInstance(instance);
                appPid=R32(appBytes,56);if(appPid==0U)throw new ArgumentException();
            }
            catch{if(reason==BvePidMismatch)return false;reason=AppDirectoryInvalid;return false;}

            byte[] telemetryBytes;
            string telemetryName;
            try{telemetryName=DataPlaneProtocol.TelemetryName((UInt32)bveProcessId,instance);}catch{reason=AppDirectoryInvalid;return false;}
            if(!TryReadStable(telemetryName,DataPlaneProtocol.DirectorySize,out telemetryBytes,out reason,TelemetryDirectoryMissing,TelemetryDirectoryTorn))return false;
            TelemetryDirectory directory;
            try{directory=DataPlaneProtocol.DecodeTelemetryDirectory(telemetryBytes);}catch{reason=TelemetryDirectoryInvalid;return false;}
            UInt32 ready=DataPlaneProtocol.Published|DataPlaneProtocol.Ready;
            if((directory.State&ready)!=ready||(directory.State&(DataPlaneProtocol.Withdrawing|DataPlaneProtocol.Closed))!=0U){reason=TelemetryNotReady;return false;}
            if(directory.BvePid!=(UInt32)bveProcessId){reason=BvePidMismatch;return false;}
            if(!String.Equals(directory.AppInstance,instance,StringComparison.Ordinal)){reason=AppInstanceMismatch;return false;}
            if(directory.AppPid!=appPid){reason=AppPidMismatch;return false;}
            endpoint=new TelemetryEndpoint(directory.BvePid,directory.AppInstance,directory.AppPid,directory.Port,directory.Generation,(byte[])directory.Token.Clone(),directory.ChangeCount,directory.Capabilities);
            reason=Ok;return true;
        }

        private static bool TryReadStable(string name,int size,out byte[] bytes,out string reason,string missing,string torn)
        {
            bytes=null;reason=missing;MemoryMappedFile mapping=null;MemoryMappedViewAccessor view=null;
            try
            {
                mapping=MemoryMappedFile.OpenExisting(name,MemoryMappedFileRights.Read);
                view=mapping.CreateViewAccessor(0,size,MemoryMappedFileAccess.Read);
                for(int attempt=0;attempt<3;attempt++)
                {
                    UInt32 before=view.ReadUInt32(16);if((before&1U)!=0U)continue;
                    byte[] candidate=new byte[size];view.ReadArray(0,candidate,0,size);
                    UInt32 after=view.ReadUInt32(16);UInt32 head=R32(candidate,16);UInt32 tail=R32(candidate,size-4);
                    if(before==after&&after==head&&head==tail&&(head&1U)==0U){bytes=candidate;reason=Ok;return true;}
                }
                reason=torn;return false;
            }
            catch(System.IO.FileNotFoundException){reason=missing;return false;}
            catch{reason=missing;return false;}
            finally{if(view!=null)try{view.Dispose();}catch{}if(mapping!=null)try{mapping.Dispose();}catch{}}
        }
        private static UInt32 R32(byte[] b,int o){return (UInt32)(b[o]|(b[o+1]<<8)|(b[o+2]<<16)|(b[o+3]<<24));}
        private static bool Zero(byte[] b,int o,int n){for(int i=0;i<n;i++)if(b[o+i]!=0)return false;return true;}
    }
}
